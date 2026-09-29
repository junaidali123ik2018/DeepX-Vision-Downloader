import os
from pathlib import Path
import shutil
import subprocess
import sys

def find_iscc() -> str | None:
    # Check PATH first
    which_iscc = shutil.which("iscc")
    if which_iscc:
        return which_iscc
    
    # Common installation paths on Windows
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Users/Junaid Ali/AppData/Local/Programs/Inno Setup 6/ISCC.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None

def build():
    print("==================================================")
    print(" 1. Building App with PyInstaller...")
    print("==================================================")
    cmd_py = [sys.executable, "-m", "PyInstaller", "DeepX Vision Downloader.spec", "--noconfirm"]
    res_py = subprocess.run(cmd_py)
    if res_py.returncode != 0:
        print(f"\n[ERROR] PyInstaller build failed with code {res_py.returncode}")
        return

    print("\n==================================================")
    print(" 2. Compiling Windows Installer with Inno Setup...")
    print("==================================================")
    iscc_path = find_iscc()
    if not iscc_path:
        print("\n[ERROR] Inno Setup Compiler (ISCC.exe) not found!")
        print("Please install Inno Setup 6 (winget install JRSoftware.InnoSetup)")
        return

    print(f"Found Inno Setup compiler: {iscc_path}")
    res_inno = subprocess.run([iscc_path, "installer.iss"])
    if res_inno.returncode == 0:
        setup_file = Path("dist_installer/DeepX_Vision_Downloader_Pro_Setup_v2.5.1.exe").resolve()
        size_mb = setup_file.stat().st_size / (1024 * 1024) if setup_file.is_file() else 0
        print("\n==================================================")
        print(" [SUCCESS] Windows Setup Installer Created!")
        print(f" File: {setup_file}")
        print(f" Size: {size_mb:.2f} MB")
        print("==================================================")
        print("\nThis single .exe file can be copied to ANY Windows PC.")
        print("Double-click it on any other PC to install the app with desktop shortcuts!")
    else:
        print(f"\n[ERROR] Inno Setup compilation failed with code {res_inno.returncode}")

if __name__ == "__main__":
    build()
