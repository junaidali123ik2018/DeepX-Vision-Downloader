---
description: Always automatically rebuild dist/ and dist_installer/ whenever any code changes or bugfixes are made in HQ-Video-Downloader.
always_on: true
---

# Auto Rebuild Rule for HQ-Video-Downloader

Whenever any code modification, feature addition, or bug fix is implemented in this codebase:
1. Verify syntax and logic.
2. Commit git changes.
3. Automatically execute `build_exe.py` and `ISCC.exe installer.iss` to recompile `dist/DeepX Vision Downloader/DeepX Vision Downloader.exe` and `dist_installer/DeepX_Vision_Downloader_Pro_Setup_v2.5.1.exe`.
4. The user should NEVER have to manually remind or ask to update `dist/` or `dist_installer/`. It must always be done automatically as part of completing the task.
