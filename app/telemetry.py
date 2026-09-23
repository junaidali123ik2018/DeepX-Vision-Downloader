from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import threading
import time
from typing import Optional
import urllib.parse
import urllib.request
import requests

from app.version import APP_VERSION

# Default Cloud Bridge URL (Firebase Realtime Database REST API)
# Owner can change this anytime in Settings or in Admin Dashboard
DEFAULT_CLOUD_BRIDGE_URL = "https://deepx-vision-telemetry-default-rtdb.firebaseio.com"

# Default Owner Admin Password (SHA-256 hash of "admin123" by default, customizable)
DEFAULT_ADMIN_PASSWORD_HASH = hashlib.sha256(b"admin123").hexdigest()

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "DeepX_Vision" / "telemetry"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_BAN_CACHE = CACHE_DIR / "device_ban.json"
OWNER_CONFIG_FILE = CACHE_DIR / "admin_config.json"


@dataclass
class DeviceInfo:
    machine_id: str
    country: str = "Unknown"
    city: str = "Unknown"
    country_code: str = "XX"
    os_name: str = ""
    app_version: str = APP_VERSION
    is_pro: bool = False
    tier: str = "Trial"
    first_seen: str = ""
    last_seen: str = ""
    download_count: int = 0
    is_banned: bool = False
    ban_reason: str = ""


class TelemetryService:
    def __init__(self) -> None:
        self._cloud_url = self._get_configured_cloud_url()
        self._cached_geo: dict[str, str] | None = None
        self._is_banned_local = False
        self._ban_reason_local = ""
        self._load_local_ban_cache()

    def _get_configured_cloud_url(self) -> str:
        if OWNER_CONFIG_FILE.is_file():
            try:
                data = json.loads(OWNER_CONFIG_FILE.read_text(encoding="utf-8"))
                return data.get("cloud_bridge_url") or DEFAULT_CLOUD_BRIDGE_URL
            except Exception:
                pass
        return DEFAULT_CLOUD_BRIDGE_URL

    def set_configured_cloud_url(self, url: str) -> None:
        clean = url.strip().rstrip("/")
        self._cloud_url = clean
        try:
            cfg = {}
            if OWNER_CONFIG_FILE.is_file():
                cfg = json.loads(OWNER_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["cloud_bridge_url"] = clean
            OWNER_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_cloud_url(self) -> str:
        return self._cloud_url

    def get_admin_password_hash(self) -> str:
        if OWNER_CONFIG_FILE.is_file():
            try:
                data = json.loads(OWNER_CONFIG_FILE.read_text(encoding="utf-8"))
                return data.get("admin_password_hash") or DEFAULT_ADMIN_PASSWORD_HASH
            except Exception:
                pass
        return DEFAULT_ADMIN_PASSWORD_HASH

    def set_admin_password(self, new_password: str) -> None:
        h = hashlib.sha256(new_password.strip().encode("utf-8")).hexdigest()
        try:
            cfg = {}
            if OWNER_CONFIG_FILE.is_file():
                cfg = json.loads(OWNER_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["admin_password_hash"] = h
            OWNER_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass

    def verify_admin_password(self, password_input: str) -> bool:
        if not password_input:
            return False
        input_hash = hashlib.sha256(password_input.strip().encode("utf-8")).hexdigest()
        return input_hash == self.get_admin_password_hash()

    def _load_local_ban_cache(self) -> None:
        if LOCAL_BAN_CACHE.is_file():
            try:
                data = json.loads(LOCAL_BAN_CACHE.read_text(encoding="utf-8"))
                self._is_banned_local = bool(data.get("is_banned", False))
                self._ban_reason_local = str(data.get("ban_reason", ""))
            except Exception:
                pass

    def _save_local_ban_cache(self, is_banned: bool, reason: str) -> None:
        self._is_banned_local = is_banned
        self._ban_reason_local = reason
        try:
            data = {"is_banned": is_banned, "ban_reason": reason, "updated_at": datetime.now(timezone.utc).isoformat()}
            LOCAL_BAN_CACHE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -------------------------------------------------------------
    # Geolocation Lookup (Fast, Anonymous, 100% Free)
    # -------------------------------------------------------------
    def _fetch_geo(self) -> dict[str, str]:
        if self._cached_geo:
            return self._cached_geo

        geo = {"country": "Unknown", "city": "Unknown", "country_code": "XX"}
        try:
            req = urllib.request.Request(
                "http://ip-api.com/json/?fields=status,country,city,countryCode",
                headers={"User-Agent": "DeepX-Telemetry/2.5"},
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    geo["country"] = data.get("country", "Unknown")
                    geo["city"] = data.get("city", "Unknown")
                    geo["country_code"] = data.get("countryCode", "XX")
                    self._cached_geo = geo
                    return geo
        except Exception:
            pass

        try:
            req2 = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "DeepX-Telemetry/2.5"})
            with urllib.request.urlopen(req2, timeout=3.5) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8"))
                geo["country"] = data2.get("country_name", "Unknown")
                geo["city"] = data2.get("city", "Unknown")
                geo["country_code"] = data2.get("country_code", "XX")
                self._cached_geo = geo
                return geo
        except Exception:
            pass

        return geo

    # -------------------------------------------------------------
    # Remote Device Ban / Unban Check & Kill Switch
    # -------------------------------------------------------------
    def check_device_ban(self, machine_id: str | None = None) -> tuple[bool, str]:
        """
        Queries the cloud bridge to check if this machine_id is banned.
        Returns: (is_banned: bool, ban_reason: str)
        """
        if not machine_id:
            try:
                from app.license import license_mgr
                machine_id = license_mgr.machine_id
            except Exception:
                machine_id = "UNKNOWN"

        # If locally cached as banned, fail immediately
        if self._is_banned_local:
            return True, self._ban_reason_local or "Your device has been disabled by the administrator."

        if not self._cloud_url or "firebaseio.com" not in self._cloud_url:
            return False, ""

        clean_mid = machine_id.replace("/", "_").replace(".", "_")
        url = f"{self._cloud_url}/banned_devices/{clean_mid}.json"

        try:
            resp = requests.get(url, timeout=3.0)
            if resp.status_code == 200 and resp.text.strip() not in {"null", "{}"}:
                data = resp.json()
                if isinstance(data, dict) and data.get("banned", False):
                    reason = data.get("reason") or "Your device has been suspended by administrator."
                    self._save_local_ban_cache(True, reason)
                    return True, reason
                else:
                    self._save_local_ban_cache(False, "")
                    return False, ""
            elif resp.status_code == 200 and resp.text.strip() in {"null", "{}"}:
                self._save_local_ban_cache(False, "")
                return False, ""
        except Exception:
            pass

        # Return local cache status if offline
        return self._is_banned_local, self._ban_reason_local

    def ban_device(self, machine_id: str, reason: str = "Unauthorized use") -> tuple[bool, str]:
        """Marks machine_id as banned on the cloud bridge."""
        if not self._cloud_url:
            return False, "Cloud bridge URL is not configured."

        clean_mid = machine_id.replace("/", "_").replace(".", "_")
        url = f"{self._cloud_url}/banned_devices/{clean_mid}.json"

        payload = {
            "machine_id": machine_id,
            "banned": True,
            "reason": reason.strip() or "Device banned by owner",
            "banned_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            resp = requests.put(url, json=payload, timeout=6.0)
            if resp.status_code in {200, 204}:
                # Also update device record status
                dev_url = f"{self._cloud_url}/devices/{clean_mid}/is_banned.json"
                requests.put(dev_url, json=True, timeout=4.0)
                return True, f"Device {machine_id} has been banned successfully!"
            return False, f"Cloud bridge returned status {resp.status_code}"
        except Exception as ex:
            return False, f"Failed to ban device: {ex}"

    def unban_device(self, machine_id: str) -> tuple[bool, str]:
        """Removes machine_id from the cloud banned list."""
        if not self._cloud_url:
            return False, "Cloud bridge URL is not configured."

        clean_mid = machine_id.replace("/", "_").replace(".", "_")
        url = f"{self._cloud_url}/banned_devices/{clean_mid}.json"

        try:
            resp = requests.delete(url, timeout=6.0)
            if resp.status_code in {200, 204}:
                dev_url = f"{self._cloud_url}/devices/{clean_mid}/is_banned.json"
                requests.put(dev_url, json=False, timeout=4.0)
                # If current machine was unbanned locally
                if self._is_banned_local:
                    self._save_local_ban_cache(False, "")
                return True, f"Device {machine_id} has been unbanned!"
            return False, f"Cloud bridge returned status {resp.status_code}"
        except Exception as ex:
            return False, f"Failed to unban device: {ex}"

    # -------------------------------------------------------------
    # Startup Heartbeat & Download Telemetry Pings
    # -------------------------------------------------------------
    def report_session_start_async(self, machine_id: str, is_pro: bool, tier: str) -> None:
        """Fires background thread to send startup session heartbeat."""
        def _worker():
            self._report_session_start(machine_id, is_pro, tier)

        threading.Thread(target=_worker, daemon=True).start()

    def _report_session_start(self, machine_id: str, is_pro: bool, tier: str) -> None:
        if not self._cloud_url or "firebaseio.com" not in self._cloud_url:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        clean_mid = machine_id.replace("/", "_").replace(".", "_")
        geo = self._fetch_geo()

        os_str = f"{platform.system()} {platform.release()}"

        payload = {
            "machine_id": machine_id,
            "country": geo.get("country", "Unknown"),
            "city": geo.get("city", "Unknown"),
            "country_code": geo.get("country_code", "XX"),
            "os_name": os_str,
            "app_version": APP_VERSION,
            "is_pro": is_pro,
            "tier": tier,
            "last_seen": now_iso,
        }

        url = f"{self._cloud_url}/devices/{clean_mid}.json"
        try:
            # Check if record exists to keep first_seen
            check_resp = requests.get(url, timeout=3.0)
            if check_resp.status_code == 200 and check_resp.text.strip() not in {"null", "{}"}:
                existing = check_resp.json()
                if isinstance(existing, dict) and "first_seen" in existing:
                    payload["first_seen"] = existing["first_seen"]
                else:
                    payload["first_seen"] = now_iso
            else:
                payload["first_seen"] = now_iso

            requests.patch(url, json=payload, timeout=5.0)
        except Exception:
            pass

    def report_download_event_async(self, platform_name: str, quality: str, is_pro: bool) -> None:
        """Fires background thread to increment download stats."""
        def _worker():
            self._report_download_event(platform_name, quality, is_pro)

        threading.Thread(target=_worker, daemon=True).start()

    def _report_download_event(self, platform_name: str, quality: str, is_pro: bool) -> None:
        if not self._cloud_url or "firebaseio.com" not in self._cloud_url:
            return

        clean_plat = platform_name.lower().strip()
        url = f"{self._cloud_url}/analytics/downloads.json"
        now_iso = datetime.now(timezone.utc).isoformat()

        event = {
            "platform": clean_plat,
            "quality": quality,
            "is_pro": is_pro,
            "timestamp": now_iso,
        }

        try:
            requests.post(url, json=event, timeout=4.0)
        except Exception:
            pass

    # -------------------------------------------------------------
    # Owner Dashboard Aggregated Data Retrieval
    # -------------------------------------------------------------
    def fetch_dashboard_data(self) -> dict:
        """
        Retrieves all devices, banned devices, and download analytics for Owner Dashboard.
        """
        result = {
            "devices": [],
            "banned_devices": [],
            "total_devices": 0,
            "pro_devices": 0,
            "trial_devices": 0,
            "banned_count": 0,
            "total_downloads": 0,
            "countries": {},
            "cities": {},
            "platforms": {"youtube": 0, "tiktok": 0, "instagram": 0, "facebook": 0, "other": 0},
            "recent_downloads": [],
            "connected": False,
            "error_message": "",
        }

        if not self._cloud_url or "firebaseio.com" not in self._cloud_url:
            result["error_message"] = "Cloud Bridge URL not configured. Enter your Firebase URL in Dashboard Settings."
            return result

        try:
            # 1. Fetch devices
            dev_resp = requests.get(f"{self._cloud_url}/devices.json", timeout=6.0)
            if dev_resp.status_code == 200 and dev_resp.text.strip() not in {"null", "{}"}:
                raw_devs = dev_resp.json()
                if isinstance(raw_devs, dict):
                    for _, d in raw_devs.items():
                        if isinstance(d, dict):
                            result["devices"].append(d)
                            country = d.get("country") or "Unknown"
                            city = d.get("city") or "Unknown"
                            result["countries"][country] = result["countries"].get(country, 0) + 1
                            if city != "Unknown":
                                result["cities"][city] = result["cities"].get(city, 0) + 1
                            if d.get("is_pro"):
                                result["pro_devices"] += 1
                            else:
                                result["trial_devices"] += 1

            result["total_devices"] = len(result["devices"])

            # 2. Fetch banned devices
            ban_resp = requests.get(f"{self._cloud_url}/banned_devices.json", timeout=6.0)
            if ban_resp.status_code == 200 and ban_resp.text.strip() not in {"null", "{}"}:
                raw_bans = ban_resp.json()
                if isinstance(raw_bans, dict):
                    for _, b in raw_bans.items():
                        if isinstance(b, dict):
                            result["banned_devices"].append(b)

            result["banned_count"] = len(result["banned_devices"])

            # Mark devices in the devices list that are banned
            banned_mids = {b.get("machine_id") for b in result["banned_devices"]}
            for dev in result["devices"]:
                if dev.get("machine_id") in banned_mids:
                    dev["is_banned"] = True

            # 3. Fetch downloads analytics
            dl_resp = requests.get(f"{self._cloud_url}/analytics/downloads.json", timeout=6.0)
            if dl_resp.status_code == 200 and dl_resp.text.strip() not in {"null", "{}"}:
                raw_dls = dl_resp.json()
                if isinstance(raw_dls, dict):
                    result["total_downloads"] = len(raw_dls)
                    for _, dl in list(raw_dls.items())[-100:]:
                        if isinstance(dl, dict):
                            p = (dl.get("platform") or "other").lower()
                            if "youtube" in p or "youtu" in p:
                                result["platforms"]["youtube"] += 1
                            elif "tiktok" in p:
                                result["platforms"]["tiktok"] += 1
                            elif "instagram" in p:
                                result["platforms"]["instagram"] += 1
                            elif "facebook" in p or "fb" in p:
                                result["platforms"]["facebook"] += 1
                            else:
                                result["platforms"]["other"] += 1
                            result["recent_downloads"].append(dl)

            result["connected"] = True
            return result
        except requests.RequestException as ex:
            result["error_message"] = f"Network error connecting to cloud bridge: {ex}"
            return result
        except Exception as ex:
            result["error_message"] = f"Telemetry fetch error: {ex}"
            return result


telemetry_service = TelemetryService()
