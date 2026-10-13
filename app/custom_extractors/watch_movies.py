from __future__ import annotations

import logging
import re
from urllib.parse import urlparse
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.watch-movies.com.pk/",
}


def is_watch_movies_url(url: str) -> bool:
    """Checks if the URL is from watch-movies.com.pk."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower().strip()
    return "watch-movies.com.pk" in u


def unpack_packer(p: str, a: int, c: int, k: list[str]) -> str:
    """
    Unpacks Dean Edwards JavaScript packer:
    eval(function(p,a,c,k,e,d){...}('...', a, c, '...'.split('|')))
    """
    def e_func(c_val: int) -> str:
        return (
            ("" if c_val < a else e_func(int(c_val / a)))
            + (chr(c_val % a + 29) if c_val % a > 35 else "0123456789abcdefghijklmnopqrstuvwxyz"[c_val % a])
        )

    word_map = {}
    for i, word in enumerate(k):
        word_map[e_func(i)] = word if word else e_func(i)

    def repl(m: re.Match) -> str:
        w = m.group(0)
        return word_map.get(w, w)

    return re.sub(r"\b\w+\b", repl, p)


def _clean_movie_title(raw_title: str) -> str:
    """Cleans site promotional text and returns clean movie title."""
    if not raw_title:
        return "WatchMovies Video"
    t = raw_title.strip()
    # Strip site branding and download text
    t = re.sub(r"\s*(?:Watch\s+Online.*|Full\s+Movie\s+Watch\s+Online.*|HD\s+Print.*|Free\s+Download.*|-?\s*Watch\s*Movies.*)$", "", t, flags=re.I).strip()
    t = re.sub(r"\s*-\s*$", "", t).strip()
    return t or "WatchMovies Video"


def extract_watch_movies(url: str, desired_quality: str = "Best Available") -> dict | None:
    """
    Extracts video metadata and streams from watch-movies.com.pk.
    Resolves embedded streams from ok.ru, pkembed.site, mxdrop, or direct streams.
    """
    clean_url = url.strip()
    try:
        req = urllib.request.Request(clean_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error("Failed to fetch watch-movies page %s: %s", clean_url, e)
        return None

    # 1. Extract and Clean Page Title
    title_m = re.search(r"<title>(.*?)</title>", html, re.I)
    raw_title = title_m.group(1) if title_m else ""
    title = _clean_movie_title(raw_title)

    # 2. Extract Thumbnail
    thumb_m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    thumbnail = thumb_m.group(1) if thumb_m else ""
    if not thumbnail:
        poster_m = re.search(r'<img[^>]+src=["\']([^"\']+(?:poster|thumb|cover)[^"\']*)["\']', html, re.I)
        if poster_m:
            thumbnail = poster_m.group(1)

    # 3. Discover all embedded iframes
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)

    # 4. Priority 1: OK.ru embed (Full multi-quality official streams)
    for ifr in iframes:
        if "ok.ru" in ifr:
            ok_id_m = re.search(r"videoembed/(\d+)", ifr)
            if ok_id_m:
                ok_id = ok_id_m.group(1)
                ok_url = f"https://ok.ru/videoembed/{ok_id}"
                try:
                    import yt_dlp
                    from app.custom_extractors import apply_custom_patches
                    apply_custom_patches()

                    ydl_opts = {
                        "quiet": True,
                        "skip_download": True,
                        "no_warnings": True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ok_info = ydl.extract_info(ok_url, download=False)
                        if ok_info and ok_info.get("formats"):
                            ok_info["title"] = title
                            ok_info["uploader"] = "Watch-Movies"
                            ok_info["creator"] = "Watch-Movies"
                            ok_info["extractor"] = "watchmoviespk"
                            ok_info["extractor_key"] = "WatchMoviesPK"
                            ok_info["platform"] = "watchmoviespk"
                            ok_info["webpage_url"] = clean_url
                            if thumbnail and not ok_info.get("thumbnail"):
                                ok_info["thumbnail"] = thumbnail
                            return ok_info
                except Exception as ok_err:
                    logger.debug("OK.ru extraction failed for %s: %s", ok_url, ok_err)

    formats: list[dict] = []

    # 5. Priority 2: pkembed.site / do7go.com (Unpack Dean Edwards packer)
    for ifr in iframes:
        ifr_clean = ifr if ifr.startswith("http") else f"https:{ifr}"
        if any(host in ifr_clean for host in ["pkembed.site", "do7go.com", "playmogo.com"]):
            try:
                emb_req = urllib.request.Request(
                    ifr_clean,
                    headers={
                        **DEFAULT_HEADERS,
                        "Referer": clean_url,
                    },
                )
                with urllib.request.urlopen(emb_req, timeout=12) as emb_resp:
                    emb_html = emb_resp.read().decode("utf-8", errors="ignore")

                # Check for packed eval JS
                packer_m = re.search(
                    r"eval\(function\(p,a,c,k,e,[rd]\)\s*\{.*?return p\}\s*\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)",
                    emb_html,
                    re.DOTALL,
                )
                if packer_m:
                    p, a, c, k = packer_m.group(1), int(packer_m.group(2)), int(packer_m.group(3)), packer_m.group(4).split("|")
                    unpacked = unpack_packer(p, a, c, k)
                    stream_urls = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', unpacked)
                    for su in stream_urls:
                        ext = "mp4" if ".mp4" in su else "m3u8"
                        formats.append({
                            "format_id": f"pkembed-{ext}",
                            "format_note": "Direct Stream",
                            "url": su,
                            "ext": ext,
                            "http_headers": {
                                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                                "Referer": ifr_clean,
                            },
                        })
                else:
                    # Direct stream URLs in embed HTML
                    direct_streams = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', emb_html)
                    for su in direct_streams:
                        ext = "mp4" if ".mp4" in su else "m3u8"
                        formats.append({
                            "format_id": f"embed-{ext}",
                            "format_note": "Direct Stream",
                            "url": su,
                            "ext": ext,
                            "http_headers": {
                                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                                "Referer": ifr_clean,
                            },
                        })
                if formats:
                    break
            except Exception as emb_err:
                logger.debug("Embed extraction failed for %s: %s", ifr_clean, emb_err)

    # 6. Priority 3: mxdrop.to / mxdrop.top
    if not formats:
        for ifr in iframes:
            ifr_clean = ifr if ifr.startswith("http") else f"https:{ifr}"
            if "mxdrop" in ifr_clean:
                try:
                    mx_req = urllib.request.Request(
                        ifr_clean,
                        headers={
                            **DEFAULT_HEADERS,
                            "Referer": clean_url,
                        },
                    )
                    with urllib.request.urlopen(mx_req, timeout=12) as mx_resp:
                        mx_html = mx_resp.read().decode("utf-8", errors="ignore")

                    packer_m = re.search(
                        r"eval\(function\(p,a,c,k,e,[rd]\)\s*\{.*?return p\}\s*\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)",
                        mx_html,
                        re.DOTALL,
                    )
                    if packer_m:
                        p, a, c, k = packer_m.group(1), int(packer_m.group(2)), int(packer_m.group(3)), packer_m.group(4).split("|")
                        unpacked = unpack_packer(p, a, c, k)
                        # Extract MDCore.wurl or direct mp4
                        wurl_m = re.search(r'MDCore\.(?:wurl|furl)\s*=\s*["\']([^"\']+)["\']', unpacked)
                        if wurl_m and wurl_m.group(1).strip():
                            raw_wurl = wurl_m.group(1).strip()
                            stream_url = raw_wurl if raw_wurl.startswith("http") else f"https:{raw_wurl}"
                            formats.append({
                                "format_id": "mxdrop-mp4",
                                "format_note": "Direct MP4",
                                "url": stream_url,
                                "ext": "mp4",
                                "http_headers": {
                                    "User-Agent": DEFAULT_HEADERS["User-Agent"],
                                    "Referer": ifr_clean,
                                },
                            })
                            break
                except Exception as mx_err:
                    logger.debug("Mxdrop extraction failed: %s", mx_err)

    if not formats:
        # 7. Fallback: check any media links directly on the page
        page_streams = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', html)
        for su in page_streams:
            formats.append({
                "format_id": "direct-stream",
                "format_note": "Direct Stream",
                "url": su,
                "ext": "mp4" if ".mp4" in su else "m3u8",
                "http_headers": {
                    "User-Agent": DEFAULT_HEADERS["User-Agent"],
                    "Referer": clean_url,
                },
            })

    if not formats:
        return None

    parsed_u = urlparse(clean_url)
    media_id = parsed_u.path.strip("/").split("/")[-1] or "video"

    return {
        "id": media_id,
        "title": title,
        "thumbnail": thumbnail,
        "formats": formats,
        "uploader": "Watch-Movies",
        "creator": "Watch-Movies",
        "extractor": "watchmoviespk",
        "extractor_key": "WatchMoviesPK",
        "platform": "watchmoviespk",
        "webpage_url": clean_url,
    }
