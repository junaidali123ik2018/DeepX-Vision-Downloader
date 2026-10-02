from __future__ import annotations

import io
from pathlib import Path
import re
from typing import Callable
import urllib.request
from urllib.parse import unquote

from PIL import Image
import yt_dlp

from app.ytdl_utils import apply_ytdl_robust_options


def parse_tiktok_playlist_url(url: str) -> tuple[str, str | None]:
    """
    If url is a TikTok playlist URL (tiktok.com/@user/playlist/Title-ID),
    extracts the profile URL and playlist name so yt-dlp doesn't crash with Unsupported URL.
    """
    m = re.search(r"tiktok\.com/@([^/?#]+)/playlist/([^/?#&]+)", url, re.I)
    if m:
        username = m.group(1)
        raw_title = m.group(2)
        # Strip trailing ID if present (e.g., Light%20triggers-7322097679696169774)
        title_part = re.sub(r"-\d+$", "", raw_title)
        clean_title = unquote(title_part)
        profile_url = f"https://www.tiktok.com/@{username}"
        return profile_url, f"TikTok: {clean_title} (@{username})"
    return url, None


def normalize_channel_url(url: str, mode: str = "videos") -> str:
    """
    Normalizes YouTube or TikTok URLs based on mode:
    mode='videos': targets /videos tab
    mode='shorts': targets /shorts tab
    mode='playlists': targets /playlists tab
    mode='playlist': direct playlist
    """
    url = url.strip().rstrip("/")
    if "youtube.com" in url or "youtu.be" in url:
        base = re.sub(r"/(videos|shorts|playlists|streams|featured|community)$", "", url)
        if "/@" in base or "/channel/" in base or "/c/" in base:
            if mode == "playlists":
                return f"{base}/playlists"
            elif mode == "videos":
                return f"{base}/videos"
            elif mode == "shorts":
                return f"{base}/shorts"
            return base
    return url


def is_youtube_channel_url(url: str) -> bool:
    """Returns True if the URL points to a YouTube channel/user rather than a single video."""
    u = url.lower().strip()
    return (
        ("youtube.com/@" in u or "youtube.com/channel/" in u or "youtube.com/c/" in u or "youtube.com/user/" in u)
        and "/watch" not in u
        and "list=" not in u
    )


def is_playlist_or_channel(url: str) -> bool:
    """Returns True if the URL points to a playlist, channel, or profile."""
    u = url.lower().strip()
    if "playlist?list=" in u or "&list=" in u or "/playlist/" in u or "/playlists" in u:
        return True
    if "youtube.com/@" in u or "youtube.com/channel/" in u or "youtube.com/c/" in u or "youtube.com/user/" in u:
        return True
    if "tiktok.com/@" in u and "/video/" not in u and "/photo/" not in u:
        return True
    if "instagram.com/" in u and not any(x in u for x in ["/p/", "/reel/", "/reels/", "/tv/", "/stories/"]):
        return True
    if "facebook.com/" in u and ("/videos" in u or "/watch" in u) and "/watch/?v=" not in u:
        return True
    if "vimeo.com/channels/" in u or "vimeo.com/showcase/" in u:
        return True
    if "dailymotion.com/playlist/" in u or "dailymotion.com/user/" in u:
        return True
    if "soundcloud.com/" in u and "/sets/" in u:
        return True
    if "twitch.tv/" in u and "/videos" in u:
        return True
    return False


def fetch_playlist_info(
    url: str,
    max_items: int = 0,
    mode: str = "auto",
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[str, list[dict]]:
    """Fetches video titles, URLs, and metadata from a playlist or channel."""
    tiktok_profile, extracted_title = parse_tiktok_playlist_url(url)
    if tiktok_profile != url:
        norm_url = tiktok_profile
    else:
        norm_url = normalize_channel_url(url, mode="videos" if mode == "all_videos" else "playlists" if mode == "all_playlists" else "auto")

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        from ui.browser_window import detect_platform_from_url, get_cookie_file_path
        platform = detect_platform_from_url(norm_url)
        p_cookie = get_cookie_file_path(platform)
        if p_cookie.is_file() and p_cookie.stat().st_size > 50:
            ydl_opts["cookiefile"] = str(p_cookie)
        else:
            b_cookie = get_cookie_file_path("browser")
            if b_cookie.is_file() and b_cookie.stat().st_size > 50:
                ydl_opts["cookiefile"] = str(b_cookie)
    except Exception:
        pass

    if max_items and max_items > 0:
        ydl_opts["playlist_items"] = f"1:{max_items}"

    apply_ytdl_robust_options(ydl_opts)

    def _parse_entry(e, default_media_type="video") -> dict | None:
        v_url = e.get("url")
        v_id = e.get("id")
        is_short = default_media_type == "short" or "/shorts/" in str(v_url or "")
        if v_url and not v_url.startswith("http"):
            v_url = f"https://www.youtube.com/shorts/{v_url}" if is_short else f"https://www.youtube.com/watch?v={v_url}"
        elif not v_url and v_id:
            v_url = f"https://www.youtube.com/shorts/{v_id}" if is_short else f"https://www.youtube.com/watch?v={v_id}"

        if not v_url:
            return None

        raw_th = e.get("thumbnail") or e.get("thumbnails")
        thumb_url = None
        if isinstance(raw_th, str):
            thumb_url = raw_th
        elif isinstance(raw_th, list) and raw_th:
            for t in reversed(raw_th):
                if isinstance(t, dict) and t.get("url"):
                    thumb_url = t.get("url")
                    break
                elif isinstance(t, str):
                    thumb_url = t
                    break

        return {
            "id": v_id or "",
            "title": e.get("title") or ("Untitled Short" if is_short else "Untitled Video"),
            "url": v_url,
            "duration": e.get("duration"),
            "thumbnail": thumb_url,
            "thumbnail_url": thumb_url,
            "media_type": "short" if is_short else default_media_type,
        }

    # Special handling: For full YouTube channel in "all_videos" mode, grab BOTH videos and shorts
    if is_youtube_channel_url(url) and mode == "all_videos":
        if progress_callback:
            progress_callback("Analyzing channel videos & Shorts...")
        try:
            videos_url = normalize_channel_url(url, mode="videos")
            shorts_url = normalize_channel_url(url, mode="shorts")
            title = extracted_title or "YouTube Channel"
            results = []
            seen_ids = set()

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1. Fetch regular videos
                try:
                    info_v = ydl.extract_info(videos_url, download=False)
                    if info_v:
                        title = extracted_title or info_v.get("title") or info_v.get("uploader") or title
                        for e in (info_v.get("entries") or []):
                            if not e:
                                continue
                            p = _parse_entry(e, default_media_type="video")
                            if p and p["id"] not in seen_ids:
                                seen_ids.add(p["id"])
                                results.append(p)
                except Exception:
                    pass

                # 2. Fetch shorts
                try:
                    info_s = ydl.extract_info(shorts_url, download=False)
                    if info_s:
                        if title == "YouTube Channel":
                            title = extracted_title or info_s.get("title") or info_s.get("uploader") or title
                        for e in (info_s.get("entries") or []):
                            if not e:
                                continue
                            p = _parse_entry(e, default_media_type="short")
                            if p and p["id"] not in seen_ids:
                                seen_ids.add(p["id"])
                                results.append(p)
                except Exception:
                    pass

            if len(results) > 1:
                for idx, p in enumerate(results, 1):
                    raw = p.get("title", "")
                    clean_raw = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", raw)
                    p["title"] = f"{idx:02d}. {clean_raw or raw or 'Video'}"
                    p["index"] = idx
            elif len(results) == 1:
                results[0]["index"] = 1

            return title, results
        except Exception as exc:
            if progress_callback:
                progress_callback(f"Notice: {exc}")
            return extracted_title or "YouTube Channel", []

    if progress_callback:
        progress_callback("Analyzing playlist / channel...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(norm_url, download=False)
            if not info:
                return extracted_title or "Unknown Playlist", []

            title = extracted_title or info.get("title") or info.get("uploader") or "Playlist / Channel"
            raw_entries = info.get("entries") or []

            entries = []
            for item in raw_entries:
                if not item:
                    continue
                if item.get("_type") == "playlist" and item.get("entries"):
                    for sub in item.get("entries"):
                        if sub:
                            entries.append(sub)
                else:
                    entries.append(item)

            results = []
            for e in entries:
                parsed = _parse_entry(e, default_media_type="video")
                if parsed:
                    results.append(parsed)

            if len(results) > 1:
                for idx, p in enumerate(results, 1):
                    raw = p.get("title", "")
                    clean_raw = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", raw)
                    p["title"] = f"{idx:02d}. {clean_raw or raw or 'Video'}"
                    p["index"] = idx
            elif len(results) == 1:
                results[0]["index"] = 1

            return title, results
    except Exception as exc:
        if progress_callback:
            progress_callback(f"Notice: {exc}")
        return extracted_title or "Playlist / Channel", []


def fetch_channel_all_playlists(
    url: str,
    max_playlists: int = 50,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[str, list[dict]]:
    """
    Fetches all playlists belonging to a YouTube channel or creator profile.
    Returns (channel_name, list_of_playlists) where each playlist has:
    {'id', 'title', 'url', 'item_count', 'videos': []}
    """
    url_clean = url.strip()

    # Check if a single playlist link was provided in All Playlists mode
    if "list=" in url_clean or ("/playlist/" in url_clean and "tiktok.com" not in url_clean):
        title, videos = fetch_playlist_info(url_clean, max_items=0, progress_callback=progress_callback)
        return title, [{
            "id": "direct_pl_1",
            "title": title,
            "url": url_clean,
            "item_count": len(videos),
            "videos": videos,
        }]

    tiktok_profile, ext_title = parse_tiktok_playlist_url(url_clean)
    if tiktok_profile != url_clean or ("tiktok.com/@" in url_clean and "/video/" not in url_clean):
        target = tiktok_profile if tiktok_profile != url_clean else url_clean
        title, videos = fetch_playlist_info(target, max_items=0, progress_callback=progress_callback)
        return title, [{
            "id": "tiktok_pl_1",
            "title": ext_title or f"TikTok: {title}",
            "url": target,
            "item_count": len(videos),
            "videos": videos,
        }]

    target_url = normalize_channel_url(url_clean, mode="playlists")

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if max_playlists > 0:
        ydl_opts["playlist_items"] = f"1:{max_playlists}"

    apply_ytdl_robust_options(ydl_opts)

    if progress_callback:
        progress_callback("Fetching creator playlists...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            if not info:
                return "Channel Playlists", []

            channel_title = info.get("title") or info.get("uploader") or "Channel Playlists"
            raw_entries = list(info.get("entries") or [])

            playlists = []
            for e in raw_entries:
                if not e:
                    continue
                pl_url = e.get("url")
                pl_id = e.get("id")
                if pl_url and not pl_url.startswith("http"):
                    pl_url = f"https://www.youtube.com/playlist?list={pl_url}"
                elif not pl_url and pl_id:
                    pl_url = f"https://www.youtube.com/playlist?list={pl_id}"

                if not pl_url:
                    continue

                pl_thumb = None
                raw_th = e.get("thumbnails") or e.get("thumbnail")
                if isinstance(raw_th, list) and raw_th:
                    pl_thumb = raw_th[-1].get("url")
                elif isinstance(raw_th, str):
                    pl_thumb = raw_th

                playlists.append({
                    "id": pl_id or pl_url,
                    "title": e.get("title") or "Untitled Playlist",
                    "url": pl_url,
                    "item_count": e.get("playlist_count") or e.get("item_count"),
                    "thumbnail_url": pl_thumb,
                    "videos": [],  # Loaded on demand when user clicks arrow or downloads
                })

            return channel_title, playlists
    except Exception as exc:
        err_msg = str(exc)
        if "does not have a playlists tab" in err_msg or "playlists tab" in err_msg:
            # Channel has no playlists tab
            return "Channel Playlists", []
        raise


_THUMBNAIL_CACHE: dict[str, Image.Image] = {}


def get_remote_image(url: str, size: tuple[int, int] = (220, 130)) -> Image.Image | None:
    """Fetches and resizes a remote image, with in-memory caching."""
    if not url:
        return None
    cache_key = f"{url}_{size[0]}x{size[1]}"
    if cache_key in _THUMBNAIL_CACHE:
        return _THUMBNAIL_CACHE[cache_key]

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        u_low = url.lower()
        if "instagram" in u_low or "fbcdn" in u_low:
            headers["Referer"] = "https://www.instagram.com/"
        elif "tiktok" in u_low or "byteoversea" in u_low or "ibytedtos" in u_low:
            headers["Referer"] = "https://www.tiktok.com/"
        elif "youtube" in u_low or "ytimg" in u_low or "ggpht" in u_low:
            headers["Referer"] = "https://www.youtube.com/"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            img = img.resize(size, Image.Resampling.LANCZOS)
            _THUMBNAIL_CACHE[cache_key] = img
            return img
    except Exception:
        return None


def normalize_creator_input(raw: str, platform: str = "youtube") -> str:
    """Normalizes @username, partial usernames, or links to a full profile/channel URL."""
    s = raw.strip()
    if not s:
        return ""
    if "instagram.com" in s.lower():
        return s
    if "tiktok.com" in s.lower():
        return s
    if "youtube.com" in s.lower() or "youtu.be" in s.lower():
        return s
    if platform.lower() == "instagram":
        if s.startswith("@"):
            s = s[1:]
        if not s.startswith("http"):
            return f"https://www.instagram.com/{s}/"
        return s
    elif platform.lower() == "tiktok":
        if not s.startswith("@") and not s.startswith("http"):
            s = f"@{s}"
        if not s.startswith("http"):
            return f"https://www.tiktok.com/{s}"
        return s
    else:
        if s.startswith("@"):
            return f"https://www.youtube.com/{s}"
        if not s.startswith("http://") and not s.startswith("https://"):
            if "/" not in s and "." not in s:
                return f"https://www.youtube.com/@{s}"
            return f"https://{s}"
        return s


def _fetch_instagram_profile_api(username: str, cookies_source: str | None = None) -> tuple[dict, list[dict]] | None:
    """
    Attempts to query Instagram's web profile API using provided cookies (if any).
    Returns (user_info, posts_list) or None if blocked/unauthenticated.
    """
    import requests
    import http.cookiejar

    clean_user = username.strip().lstrip("@")
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_user}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/{clean_user}/",
    }

    session = requests.Session()
    if not cookies_source:
        try:
            from ui.browser_window import get_cookie_file_path
            p_cookie = get_cookie_file_path("instagram")
            if p_cookie.is_file() and p_cookie.stat().st_size > 50:
                cookies_source = str(p_cookie)
            else:
                b_cookie = get_cookie_file_path("browser")
                if b_cookie.is_file() and b_cookie.stat().st_size > 50:
                    cookies_source = str(b_cookie)
        except Exception:
            pass

    if cookies_source:
        p = Path(cookies_source)
        if p.is_file():
            try:
                cj = http.cookiejar.MozillaCookieJar(str(p))
                cj.load(ignore_discard=True, ignore_expires=True)
                session.cookies.update(cj)
            except Exception:
                pass
        else:
            try:
                import yt_dlp.cookies
                cj = yt_dlp.cookies.extract_cookies_from_browser(cookies_source)
                if cj:
                    session.cookies.update(cj)
            except Exception:
                pass

    try:
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            user_data = data.get("data", {}).get("user", {})
            if user_data:
                full_name = user_data.get("full_name") or clean_user
                avatar = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
                edges = user_data.get("edge_owner_to_timeline_media", {}).get("edges", [])
                posts = []
                for idx, edge in enumerate(edges, 1):
                    node = edge.get("node", {})
                    if not node:
                        continue
                    shortcode = node.get("shortcode") or node.get("id")
                    caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                    raw_text = caption_edges[0].get("node", {}).get("text") if caption_edges else None
                    title = raw_text.split("\n")[0][:80] if raw_text else f"Post #{idx}"
                    post_url = f"https://www.instagram.com/p/{shortcode}/"
                    thumb = node.get("display_url")
                    posts.append({
                        "id": node.get("id") or shortcode,
                        "title": title,
                        "url": post_url,
                        "thumbnail": thumb,
                        "thumbnail_url": thumb,
                        "duration": node.get("video_duration"),
                        "is_video": node.get("is_video", False),
                    })
                return {
                    "channel_title": full_name,
                    "uploader": clean_user,
                    "handle": f"@{clean_user}",
                    "avatar_url": avatar,
                    "total_posts": len(posts),
                }, posts
    except Exception:
        pass
    return None


def fetch_instagram_catalog(
    profile_input: str,
    max_items: int = 40,
    progress_callback: Callable[[str], None] | None = None,
    cookies_source: str | None = None,
) -> dict:
    """
    Fetches Instagram profile posts/reels or single post/reel media.
    Handles both direct media links and creator usernames gracefully.
    """
    raw = profile_input.strip()
    if not raw:
        return {"channel_title": "Instagram", "uploader": "", "handle": "", "posts": [], "total_posts": 0, "requires_auth": False}

    # Case 1: Direct Post or Reel URL (e.g. /reel/, /reels/, /p/, /tv/)
    is_direct_post = any(x in raw.lower() for x in ["/reel/", "/reels/", "/p/", "/tv/"])
    if is_direct_post:
        if progress_callback:
            progress_callback("Analyzing Instagram post/reel...")
        clean_url = raw if raw.startswith("http") else f"https://{raw}"
        ydl_opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        if cookies_source:
            if Path(cookies_source).is_file():
                ydl_opts["cookiefile"] = cookies_source
            else:
                ydl_opts["cookiesfrombrowser"] = (cookies_source,)

        apply_ytdl_robust_options(ydl_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                if info:
                    uploader = info.get("uploader") or "Instagram Creator"
                    title = info.get("title") or info.get("description") or f"Reel by @{uploader}"
                    if len(title) > 75:
                        title = title[:72] + "..."
                    raw_th = info.get("thumbnail") or info.get("thumbnails")
                    thumb_url = None
                    if isinstance(raw_th, str):
                        thumb_url = raw_th
                    elif isinstance(raw_th, list) and raw_th:
                        for t in reversed(raw_th):
                            if isinstance(t, dict) and t.get("url"):
                                thumb_url = t.get("url")
                                break
                            elif isinstance(t, str):
                                thumb_url = t
                                break
                    post = {
                        "id": info.get("id") or "ig_media",
                        "title": title,
                        "url": clean_url,
                        "thumbnail": thumb_url,
                        "thumbnail_url": thumb_url,
                        "duration": info.get("duration"),
                    }
                    return {
                        "channel_title": f"@{uploader}",
                        "uploader": uploader,
                        "handle": f"@{uploader}",
                        "channel_url": clean_url,
                        "avatar_url": thumb_url,
                        "posts": [post],
                        "total_posts": 1,
                        "requires_auth": False,
                    }
        except Exception as e:
            if progress_callback:
                progress_callback(f"Notice: {e}")
            return {
                "channel_title": "Instagram Media",
                "uploader": "",
                "handle": "",
                "channel_url": clean_url,
                "avatar_url": None,
                "posts": [],
                "total_posts": 0,
                "requires_auth": True,
                "error_msg": str(e),
            }

    # Case 2: Profile / Username search
    clean_url = normalize_creator_input(raw, platform="instagram")
    m = re.search(r"instagram\.com/([^/?#]+)", clean_url)
    username = m.group(1) if m else raw.lstrip("@").strip()
    handle = f"@{username}"

    if progress_callback:
        progress_callback(f"Fetching Instagram profile for {handle}...")

    # First attempt: Try extracting profile via In-App Browser headless engine
    try:
        from ui.browser_window import extract_instagram_via_process
        h_data = extract_instagram_via_process(username)
        if h_data and h_data.get("posts"):
            posts = h_data.get("posts", [])
            uploader = h_data.get("uploader") or username
            avatar = h_data.get("avatar") or (posts[0].get("thumbnail_url") if posts else None)
            return {
                "channel_title": f"@{uploader}",
                "uploader": uploader,
                "handle": f"@{uploader}",
                "channel_url": clean_url,
                "avatar_url": avatar,
                "posts": posts,
                "total_posts": len(posts),
                "total_account_posts": h_data.get("total_account_posts", ""),
                "guest_limit_reached": h_data.get("guest_limit_reached", False),
                "is_authenticated": h_data.get("is_authenticated", False),
                "requires_auth": False,
            }
    except Exception:
        pass

    # Second attempt: Try fetching using cookies/session via API
    api_res = _fetch_instagram_profile_api(username, cookies_source=cookies_source)
    if api_res:
        user_info, posts = api_res
        return {
            "channel_title": user_info.get("channel_title") or handle,
            "uploader": user_info.get("uploader") or username,
            "handle": handle,
            "channel_url": clean_url,
            "avatar_url": user_info.get("avatar_url") or (posts[0].get("thumbnail_url") if posts else None),
            "posts": posts,
            "total_posts": len(posts),
            "requires_auth": False,
        }

    # If unauthenticated or Instagram blocked profile scraping:
    return {
        "channel_title": handle,
        "uploader": username,
        "handle": handle,
        "channel_url": clean_url,
        "avatar_url": None,
        "posts": [],
        "total_posts": 0,
        "requires_auth": True,
    }


def fetch_channel_catalog(
    channel_input: str,
    max_playlists: int = 50,
    platform: str = "youtube",
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """
    Fetches full creator catalog (channel info, 'All Files' URL, and visual playlist items).
    Returns dict:
    {
        'channel_title': str,
        'uploader': str,
        'handle': str,
        'channel_url': str,
        'avatar_url': str | None,
        'all_videos_url': str,
        'estimated_videos': int | None,
        'playlists': list[dict],
        'total_playlists': int
    }
    """
    clean_url = normalize_creator_input(channel_input, platform=platform)

    # Check TikTok
    tiktok_profile, ext_title = parse_tiktok_playlist_url(clean_url)
    if tiktok_profile != clean_url or ("tiktok.com/@" in clean_url and "/video/" not in clean_url):
        target = tiktok_profile if tiktok_profile != clean_url else clean_url
        if progress_callback:
            progress_callback("Analyzing TikTok creator profile...")
        title, vids = fetch_playlist_info(target, max_items=0, progress_callback=progress_callback)
        m = re.search(r"tiktok\.com/@([^/?#]+)", target)
        handle = f"@{m.group(1)}" if m else title
        first_thumb = (vids[0].get("thumbnail_url") or vids[0].get("thumbnail")) if vids else None
        return {
            "channel_title": title or handle,
            "uploader": title or handle,
            "handle": handle,
            "channel_url": target,
            "avatar_url": first_thumb,
            "all_videos_url": target,
            "estimated_videos": len(vids),
            "playlists": [{
                "id": "tiktok_all_1",
                "title": ext_title or f"{title}'s Collection",
                "url": target,
                "item_count": len(vids),
                "thumbnail_url": first_thumb,
                "videos": vids,
            }],
            "total_playlists": 1,
        }

    # YouTube or other platforms
    if progress_callback:
        progress_callback("Fetching creator playlists and channel info...")

    playlists_url = normalize_channel_url(clean_url, mode="playlists")
    videos_url = normalize_channel_url(clean_url, mode="videos")
    shorts_url = normalize_channel_url(clean_url, mode="shorts")

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if max_playlists > 0:
        ydl_opts["playlist_items"] = f"1:{max_playlists}"

    avatar_url = None
    channel_title = "Creator Channel"
    uploader = ""
    handle = ""
    estimated_videos = None
    playlists = []

    m_handle = re.search(r"/@([^/?#]+)", clean_url)
    if m_handle:
        handle = f"@{m_handle.group(1)}"

    apply_ytdl_robust_options(ydl_opts)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlists_url, download=False)
            if info:
                channel_title = info.get("title") or info.get("channel") or info.get("uploader") or channel_title
                channel_title = re.sub(r" - (Playlists|Videos)$", "", channel_title)
                uploader = info.get("uploader") or info.get("channel") or channel_title
                thumbs = info.get("thumbnails") or []
                if thumbs and isinstance(thumbs, list):
                    avatar_url = thumbs[-1].get("url")

                raw_entries = list(info.get("entries") or [])
                for e in raw_entries:
                    if not e:
                        continue
                    pl_url = e.get("url")
                    pl_id = e.get("id")
                    if pl_url and not pl_url.startswith("http"):
                        pl_url = f"https://www.youtube.com/playlist?list={pl_url}"
                    elif not pl_url and pl_id:
                        pl_url = f"https://www.youtube.com/playlist?list={pl_id}"

                    if not pl_url:
                        continue

                    pl_thumb = None
                    raw_th = e.get("thumbnails") or e.get("thumbnail")
                    if isinstance(raw_th, list) and raw_th:
                        pl_thumb = raw_th[-1].get("url")
                    elif isinstance(raw_th, str):
                        pl_thumb = raw_th

                    playlists.append({
                        "id": pl_id or pl_url,
                        "title": e.get("title") or "Untitled Playlist",
                        "url": pl_url,
                        "item_count": e.get("playlist_count") or e.get("item_count"),
                        "thumbnail_url": pl_thumb,
                        "videos": [],
                    })
    except Exception:
        pass

    return {
        "channel_title": channel_title,
        "uploader": uploader or channel_title,
        "handle": handle or channel_title,
        "channel_url": clean_url,
        "avatar_url": avatar_url,
        "all_videos_url": videos_url,
        "all_shorts_url": shorts_url,
        "estimated_videos": estimated_videos,
        "playlists": playlists,
        "total_playlists": len(playlists),
    }
