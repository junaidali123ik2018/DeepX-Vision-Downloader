import subprocess
import sys

def build():
    print("Building DeepX Vision Downloader with PyInstaller...")
    cmd = [sys.executable, "-m", "PyInstaller", "DeepX Vision Downloader.spec", "--noconfirm"]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("\n Build completed successfully!")
        print("Output directory: dist/DeepX Vision Downloader/DeepX Vision Downloader.exe")
    else:
        print(f"\n Build failed with return code {result.returncode}")

if __name__ == "__main__":
    build()
