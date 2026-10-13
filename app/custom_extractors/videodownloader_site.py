from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import parse_qs, unquote, urlparse
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
    "Origin": "https://videodownloader.site",
    "Referer": "https://videodownloader.site/",
}


def is_videodownloader_url(url: str) -> bool:
    """Checks if the URL is from videodownloader.site (OmniSave)."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower().strip()
    return "videodownloader.site" in u or "omnisave" in u


def extract_target_from_videodownloader(url: str) -> str:
    """
    Extracts the underlying target media URL if the user submitted a videodownloader.site link.
    E.g. https://videodownloader.site/?q=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D...
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        qs = parse_qs(parsed.query)
        q_val = qs.get("q", [""])[0] or qs.get("url", [""])[0] or qs.get("sourceUrl", [""])[0]
        if q_val:
            unquoted = unquote(q_val).strip()
            if unquoted.startswith("http://") or unquoted.startswith("https://"):
                return unquoted
    except Exception:
        pass
    return url.strip()


def query_seocloud_job(
    source_url: str,
    max_wait_seconds: int = 25,
    cancel_event=None,
) -> dict | None:
    """
    Submits an extraction job to api.seocloud.biz and polls until completion.
    Returns the raw result payload dict or None if extraction failed.
    """
    if not source_url:
        return None

    submit_api = "https://api.seocloud.biz/wefeed-seo-bff/video-job/submit"
    payload_data = json.dumps({"sourceUrl": source_url}).encode("utf-8")

    submit_headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "x-request-lang": "en",
        "x-client-info": json.dumps({"timezone": "UTC"}),
    }

    try:
        req = urllib.request.Request(submit_api, data=payload_data, headers=submit_headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            submit_res = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug("Failed to submit job to seocloud: %s", e)
        return None

    task_id = submit_res.get("taskId")
    if not task_id or submit_res.get("code") != 0:
        logger.debug("seocloud submit returned error: %s", submit_res)
        return None

    status_api = f"https://api.seocloud.biz/wefeed-seo-bff/video-job/status?taskId={task_id}"
    status_headers = {
        **DEFAULT_HEADERS,
        "x-request-lang": "en",
        "x-client-info": json.dumps({"timezone": "UTC"}),
    }

    start_time = time.time()
    while (time.time() - start_time) < max_wait_seconds:
        if cancel_event and cancel_event.is_set():
            return None

        try:
            qreq = urllib.request.Request(status_api, headers=status_headers, method="GET")
            with urllib.request.urlopen(qreq, timeout=10) as qresp:
                qdata = json.loads(qresp.read().decode("utf-8", errors="ignore"))

            st = qdata.get("status")
            if st == "completed":
                result = qdata.get("result") or {}
                if result.get("formats"):
                    return result
                return None
            elif st == "failed":
                logger.debug("seocloud job failed: %s", qdata.get("errorMessage"))
                return None
        except Exception as e:
            logger.debug("seocloud poll error: %s", e)

        time.sleep(1.8)

    return None


def extract_videodownloader(url: str, desired_quality: str = "Best Available") -> dict | None:
    """
    Extracts video metadata and downloadable formats using videodownloader.site / seocloud API.
    Returns standard yt-dlp-compatible info_dict.
    """
    target_url = extract_target_from_videodownloader(url)
    if not target_url:
        return None

    # If the user pasted a MovieBox link wrapped in videodownloader.site
    from app.custom_extractors.moviebox import is_moviebox_url, extract_moviebox
    if is_moviebox_url(target_url):
        return extract_moviebox(target_url, desired_quality=desired_quality)

    result = query_seocloud_job(target_url)
    if not result:
        return None

    raw_formats = result.get("formats") or []
    valid_formats = []

    for i, fmt in enumerate(raw_formats):
        # Ignore VIP-locked or empty URLs
        direct_url = fmt.get("url")
        if not direct_url or fmt.get("vipLocked"):
            continue

        fmt_note = str(fmt.get("formatNote") or "")
        ext = str(fmt.get("ext") or "mp4").strip(".") or "mp4"

        height = fmt.get("height")
        if not height and fmt_note:
            m = re.search(r"(\d{3,4})[pP]?", fmt_note)
            if m:
                height = int(m.group(1))

        width = fmt.get("width")
        size_val = fmt.get("size")
        filesize = int(size_val) if size_val and str(size_val).isdigit() else None

        valid_formats.append({
            "url": direct_url,
            "ext": ext,
            "format_id": f"seocloud_{fmt_note or i}",
            "format_note": fmt_note or (f"{height}p" if height else "Default"),
            "height": height or 360,
            "width": width or None,
            "filesize": filesize,
            "protocol": "https",
            "http_headers": {
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Referer": "https://videodownloader.site/",
            },
        })

    if not valid_formats:
        return None

    title = result.get("title") or "Video"
    thumbnail = result.get("thumbnail") or ""
    uploader = result.get("author") or "OmniSave"
    platform = result.get("platform") or "videodownloader"

    return {
        "id": str(result.get("id") or int(time.time())),
        "title": title,
        "thumbnail": thumbnail,
        "duration": result.get("duration"),
        "uploader": uploader,
        "platform": platform,
        "formats": valid_formats,
        "webpage_url": target_url,
        "extractor": "VideoDownloaderSiteIE",
        "extractor_key": "VideoDownloaderSite",
    }
