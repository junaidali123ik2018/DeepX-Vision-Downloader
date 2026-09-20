# ⚡ DeepX Vision Downloader (Commercial Pro Edition)

![DeepX Vision Downloader](assets/brand_logo.png)

A high-performance Windows desktop application for downloading high-quality media (8K, 4K, 1080p, MP3, and Carousels) from YouTube, TikTok, Instagram, Facebook, X (Twitter), Vimeo, and 1,000+ websites.

---

## 🌟 Features

- **⚡ Multi-Platform Engine**: Supports YouTube, TikTok, Instagram, Facebook, X (Twitter), Reddit, Vimeo, SoundCloud, and 1,000+ sites powered by yt-dlp and FFmpeg.
- **💎 Commercial Licensing**:
  - Multi-tier activation (1 Month, 3 Months, 6 Months, 1 Year, Lifetime, and Family 5 PCs).
  - Cryptographic hardware binding (1 License Key = 1 Device).
  - Standalone Key Generator GUI & CLI (`tools/generate_keys.py`).
- **⏳ 5-Video Daily Free Trial**: Automatically gives free users 5 video downloads per calendar day, resetting every midnight.
- **🔄 In-App Auto-Updater**: Detects updates from remote `version.json`, downloads updates in the background, and upgrades silently with 1-click.
- **📋 Smart Clipboard Auto-Detector**: Listens for copied media links and shows a floating quick-download prompt.
- **🌐 Built-in In-App Browser**: Allows downloading restricted or age-gated videos with session cookie sync.
- **🔥 Auto-Save Hubs**: Dedicated channel & profile crawlers for YouTube, TikTok, Instagram, and X.
- **🖼️ Image & Carousel Downloader**: Batch downloads photo carousels and gallery albums.
- **📁 Creator Folder Auto-Organization**: Automatically groups downloads by creator handle or channel name.
- **🎨 Modern Fluent Dark UI**: Built with CustomTkinter, real-time download speeds, ETAs, pause/resume, and branded startup splash screen.

---

## 🚀 Getting Started

### Prerequisites
- Windows 10 or 11 (64-bit)
- Python 3.10+ (If running from source)

### Installation from Source

1. Clone repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/DeepX-Vision-Downloader.git
   cd DeepX-Vision-Downloader
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Launch application:
   ```bash
   python main.py
   ```

---

## 🔑 Key Generator (For Admin / Seller)

To generate license keys for customers:

```bash
# Launch Key Generator GUI
python tools/generate_keys.py

# Or via Command Line
python tools/generate_keys.py --tier LT --hwid DXV-D9F8-A49C
```

---

## 📦 Building Standalone Installer

To build the complete standalone Windows setup wizard (`.exe`) with Inno Setup:

```bash
python build_installer.py
```

The output file will be saved in:
`dist_installer/DeepX_Vision_Downloader_Pro_Setup_v2.5.0.exe`

---

## ⚖️ License & Credits

- **Publisher**: Junaid Ali
- **Product**: DeepX Vision Downloader Pro
- **Engine**: Powered by `yt-dlp` and `imageio-ffmpeg`.
