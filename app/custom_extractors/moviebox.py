from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs, urlparse
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://movieboxonline.org/",
    "Origin": "https://movieboxonline.org",
}


def is_moviebox_url(url: str) -> bool:
    """Checks if the URL is from MovieBox (movieboxonline.org or mirrors)."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower().strip()
    return any(domain in u for domain in ["movieboxonline.org", "themoviebox", "moviebox.ph"])


def _extract_slug(url: str) -> str:
    """Extracts the movie/show detailPath slug from a MovieBox URL."""
    parsed = urlparse(url.strip())
    path = parsed.path.strip("/")
    # Examples:
    # /detailpage/main-ladega-hindi-EUM1KmWEIR3
    # /movies/main-ladega-hindi-EUM1KmWEIR3
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("detailpage", "movies", "video"):
        return parts[1]
    if parts:
        return parts[-1]
    return ""


def extract_moviebox(url: str, desired_quality: str = "Best Available") -> dict | None:
    """
    Extracts video metadata and downloadable direct stream formats from MovieBox.
    Returns standard yt-dlp info_dict.
    """
    slug = _extract_slug(url)
    if not slug:
        return None

    parsed_url = urlparse(url)
    qs = parse_qs(parsed_url.query)
    requested_id = qs.get("id", [""])[0]
    detail_se = qs.get("detailSe", [None])[0]
    detail_ep = qs.get("detailEp", [None])[0]

    api_hosts = ["https://movieboxonline.org", "https://h5-api.aoneroom.com"]
    detail_data = None

    # 1. Fetch Subject Details via BFF API
    for host in api_hosts:
        detail_api_url = f"{host}/wefeed-h5api-bff/detail?detailPath={slug}"
        try:
            req = urllib.request.Request(
                detail_api_url,
                headers={
                    **DEFAULT_HEADERS,
                    "X-Client-Info": json.dumps({"timezone": "UTC"}),
                },
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_json = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if res_json.get("code") == 0 and res_json.get("data"):
                    detail_data = res_json["data"]
                    break
        except Exception as e:
            logger.debug("Failed to fetch MovieBox detail from %s: %s", host, e)

    # 2. Extract Subject info
    subject = {}
    resource = {}
    if detail_data:
        subject = detail_data.get("subject") or {}
        resource = detail_data.get("resource") or {}

    subject_id = str(subject.get("subjectId") or requested_id or "")
    title = (subject.get("title") or "").strip()
    duration = subject.get("duration")
    cover_obj = subject.get("cover") or {}
    thumbnail = cover_obj.get("url") if isinstance(cover_obj, dict) else ""

    # If detail API didn't provide title, attempt HTML fallback
    if not title or not subject_id:
        try:
            req_html = urllib.request.Request(
                f"https://movieboxonline.org/detailpage/{slug}",
                headers=DEFAULT_HEADERS,
            )
            with urllib.request.urlopen(req_html, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
            title_m = re.search(r"<title>(.*?)</title>", html)
            if title_m:
                raw_t = title_m.group(1)
                clean_t = re.sub(r"^(?:Watch\s+)?(.*?)(?:\s+Streaming\s+Online.*|\s+on\s+Moviebox.*|$)", r"\1", raw_t, flags=re.I).strip()
                title = clean_t or title or slug
            id_m = re.search(r'["\']subjectId["\']\s*:\s*["\']?(\d+)["\']?', html)
            if id_m:
                subject_id = subject_id or id_m.group(1)
        except Exception:
            pass

    if not title:
        title = slug.replace("-", " ").title()

    # 3. Determine Season and Episode
    se = 0
    ep = 0
    if detail_se is not None and detail_ep is not None:
        try:
            se = int(detail_se)
            ep = int(detail_ep)
        except ValueError:
            pass
    elif resource.get("seasons"):
        seasons_list = resource["seasons"]
        if seasons_list:
            first_season = seasons_list[0]
            se = first_season.get("se", 0)
            if first_season.get("allEp"):
                try:
                    ep = int(first_season["allEp"].split(",")[0])
                except (ValueError, IndexError):
                    ep = 0
            elif first_season.get("maxEp"):
                ep = 1
            else:
                ep = 0

    formats: list[dict] = []

    # 4. Fetch Stream URLs via Subject Play API
    watch_page_referer = f"https://movieboxonline.org/movies/{slug}?id={subject_id}"
    for host in api_hosts:
        play_api_url = f"{host}/wefeed-h5api-bff/subject/play?subjectId={subject_id}&se={se}&ep={ep}&detailPath={slug}"
        try:
            req = urllib.request.Request(
                play_api_url,
                headers={
                    **DEFAULT_HEADERS,
                    "Referer": watch_page_referer,
                    "X-Client-Info": json.dumps({"timezone": "Asia/Karachi"}),
                },
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                p_json = json.loads(resp.read().decode("utf-8", errors="ignore"))
                p_data = p_json.get("data") or {}
                streams = p_data.get("streams") or []
                hls_list = p_data.get("hls") or []

                for s in streams:
                    stream_url = s.get("url")
                    if not stream_url:
                        continue
                    res_str = str(s.get("resolutions") or "0")
                    height = int(res_str) if res_str.isdigit() and int(res_str) > 0 else None
                    size_val = s.get("size")
                    filesize = int(size_val) if str(size_val).isdigit() else None
                    dur_val = s.get("duration")
                    s_dur = int(dur_val) if str(dur_val).isdigit() else duration

                    format_note = f"{height}p" if height else "Direct MP4"
                    formats.append({
                        "format_id": f"http-{res_str}p" if height else "http-mp4",
                        "format_note": format_note,
                        "url": stream_url,
                        "ext": "mp4",
                        "height": height,
                        "filesize": filesize,
                        "duration": s_dur,
                        "vcodec": s.get("codecName") or "h264",
                        "http_headers": {
                            "User-Agent": DEFAULT_HEADERS["User-Agent"],
                            "Referer": "https://movieboxonline.org/",
                        },
                    })

                for h in hls_list:
                    hls_url = h.get("url")
                    if not hls_url:
                        continue
                    res_str = str(h.get("resolutions") or "0")
                    height = int(res_str) if res_str.isdigit() and int(res_str) > 0 else None
                    formats.append({
                        "format_id": f"hls-{res_str}p" if height else "hls",
                        "format_note": f"HLS {res_str}p" if height else "HLS",
                        "url": hls_url,
                        "ext": "mp4",
                        "protocol": "m3u8_native",
                        "height": height,
                        "http_headers": {
                            "User-Agent": DEFAULT_HEADERS["User-Agent"],
                            "Referer": "https://movieboxonline.org/",
                        },
                    })

                if formats:
                    break
        except Exception as e:
            logger.debug("Failed to fetch MovieBox play stream from %s: %s", host, e)

    # 5. Fallback: if play API returned no streams, check HTML trailer/contentUrl
    if not formats:
        try:
            req_html = urllib.request.Request(
                f"https://movieboxonline.org/detailpage/{slug}",
                headers=DEFAULT_HEADERS,
            )
            with urllib.request.urlopen(req_html, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
            # Search for contentUrl in schema.org JSON-LD or meta og:video
            content_urls = re.findall(r'["\'](?:contentUrl|videoAddress)["\']\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']', html)
            if not content_urls:
                content_urls = re.findall(r'<meta\s+property=["\']og:video["\']\s+content=["\']([^"\']+)["\']', html)
            if not content_urls:
                content_urls = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', html)

            for cu in set(content_urls):
                formats.append({
                    "format_id": "trailer-mp4",
                    "format_note": "Media Stream",
                    "url": cu,
                    "ext": "mp4",
                    "http_headers": {
                        "User-Agent": DEFAULT_HEADERS["User-Agent"],
                        "Referer": "https://movieboxonline.org/",
                    },
                })
        except Exception:
            pass

    if not formats:
        return None

    # Sort formats by height descending so best is at the top
    formats.sort(key=lambda f: f.get("height") or 0, reverse=True)

    return {
        "id": subject_id or slug,
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "formats": formats,
        "uploader": "MovieBox",
        "extractor": "moviebox",
        "extractor_key": "MovieBox",
        "platform": "moviebox",
        "webpage_url": url,
    }
