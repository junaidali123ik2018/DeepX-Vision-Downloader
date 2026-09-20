from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SECRET_SALT = b"DEEPX_VISION_PRO_SECRET_2026_JUNAID_ALI"

TIER_DAYS = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "LT": None,     # Lifetime
    "FAM": None,    # Family Lifetime (up to 5 PCs)
}

TIER_NAMES = {
    "1M": "1 Month Pro",
    "3M": "3 Months Pro",
    "6M": "6 Months Pro",
    "1Y": "1 Year Pro",
    "LT": "Lifetime Pro (1 PC)",
    "FAM": "Family Plan (5 PCs)",
}

DAILY_TRIAL_LIMIT = 5


def get_machine_id() -> str:
    """Generates a stable, unique Machine ID for the current computer."""
    raw_id = ""
    # Try Windows MachineGuid from Registry
    if platform.system() == "Windows":
        try:
            cmd = ['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Cryptography', '/v', 'MachineGuid']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                if "MachineGuid" in line:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        raw_id = parts[-1]
                        break
        except Exception:
            pass

    # Fallback to Node / Hostname / Processor
    if not raw_id:
        raw_id = f"{platform.node()}-{platform.processor()}-{os.environ.get('USERNAME', 'user')}"

    # Produce clean 8-character ID: DXV-XXXX-XXXX
    h = hashlib.sha256(raw_id.encode("utf-8")).hexdigest().upper()
    return f"DXV-{h[:4]}-{h[4:8]}"


def generate_license_key(tier: str = "LT", target_hwid: str = "ANY") -> str:
    """Generates a cryptographically signed license key."""
    tier = tier.upper()
    if tier not in TIER_DAYS:
        tier = "LT"
    
    # Clean HWID to pure alphanumeric
    clean_hw = target_hwid.replace("-", "").replace(" ", "").upper()
    hw_tag = clean_hw[:4] if target_hwid.upper() != "ANY" else "ANY0"
    
    # 6 random hex chars for uniqueness
    nonce = os.urandom(3).hex().upper()
    payload = f"{tier}:{clean_hw}:{nonce}"
    sig = hmac.new(SECRET_SALT, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:6].upper()
    
    # Key format: DXVP-TIER-HWTAG-NONCE-SIG (exactly 5 parts)
    return f"DXVP-{tier}-{hw_tag}-{nonce}-{sig}"


def verify_license_key(key: str, current_hwid: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Validates license key structure and signature.
    Returns: (is_valid, tier, error_reason)
    """
    if not key or not isinstance(key, str):
        return False, None, "Invalid key format."

    clean_key = key.strip().upper()
    parts = clean_key.split("-")
    if len(parts) != 5 or parts[0] != "DXVP":
        return False, None, "Key must be in format: DXVP-TIER-XXXX-XXXX-XXXX"

    _, tier, hw_tag, nonce, sig = parts
    if tier not in TIER_DAYS:
        return False, None, f"Unknown tier '{tier}'."

    clean_cur_hw = current_hwid.replace("-", "").replace(" ", "").upper()

    # Verify against ANY or current machine HWID
    valid = False
    for candidate_clean, is_any in [(clean_cur_hw, False), ("ANY", True)]:
        cand_tag = candidate_clean[:4] if not is_any else "ANY0"
        if cand_tag == hw_tag:
            payload = f"{tier}:{candidate_clean}:{nonce}"
            expected_sig = hmac.new(SECRET_SALT, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:6].upper()
            if hmac.compare_digest(sig, expected_sig):
                valid = True
                break

    if not valid:
        return False, None, "Invalid license key or signature mismatch."

    return True, tier, None


@dataclass
class LicenseData:
    key: str = ""
    tier: str = ""
    activated_date: str = ""
    expiry_date: str = ""
    bound_hwid: str = ""
    is_active: bool = False


class LicenseManager:
    _instance: Optional["LicenseManager"] = None

    @classmethod
    def get_instance(cls) -> "LicenseManager":
        if cls._instance is None:
            cls._instance = LicenseManager()
        return cls._instance

    def __init__(self) -> None:
        from app.utils import get_appdata_dir
        self.appdata_dir = get_appdata_dir("DeepX Vision Downloader")
        self.license_file = self.appdata_dir / "license.json"
        self.trial_file = self.appdata_dir / "trial.json"
        self.machine_id = get_machine_id()
        self.license_data = self._load_license()
        self._clean_trial_record()

    # -------------------------------------------------------------------------
    # License Management
    # -------------------------------------------------------------------------

    def _load_license(self) -> LicenseData:
        try:
            if self.license_file.is_file():
                raw = json.loads(self.license_file.read_text(encoding="utf-8"))
                ld = LicenseData(**raw)
                # Verify hardware binding
                if ld.is_active:
                    if ld.bound_hwid and ld.bound_hwid != self.machine_id:
                        ld.is_active = False
                    elif ld.expiry_date:
                        try:
                            exp = datetime.strptime(ld.expiry_date, "%Y-%m-%d").date()
                            if datetime.now().date() > exp:
                                ld.is_active = False
                        except Exception:
                            ld.is_active = False
                return ld
        except Exception:
            pass
        return LicenseData()

    def _save_license(self) -> None:
        try:
            self.appdata_dir.mkdir(parents=True, exist_ok=True)
            self.license_file.write_text(json.dumps(asdict(self.license_data), indent=2), encoding="utf-8")
        except Exception:
            pass

    def is_pro(self) -> bool:
        """Returns True if current machine has a valid, active Pro license."""
        if not self.license_data.is_active:
            return False
        # Hardware ID check
        if self.license_data.bound_hwid and self.license_data.bound_hwid != self.machine_id:
            return False
        # Expiry check
        if self.license_data.expiry_date:
            try:
                exp = datetime.strptime(self.license_data.expiry_date, "%Y-%m-%d").date()
                if datetime.now().date() > exp:
                    self.license_data.is_active = False
                    self._save_license()
                    return False
            except Exception:
                return False
        return True

    def get_days_remaining(self) -> Optional[int]:
        """Returns remaining days for timed licenses, or None for Lifetime."""
        if not self.is_pro():
            return 0
        if not self.license_data.expiry_date:
            return None  # Lifetime
        try:
            exp = datetime.strptime(self.license_data.expiry_date, "%Y-%m-%d").date()
            diff = (exp - datetime.now().date()).days
            return max(0, diff)
        except Exception:
            return 0

    def get_status_text(self) -> str:
        if self.is_pro():
            tier_name = TIER_NAMES.get(self.license_data.tier, "Pro Edition")
            days = self.get_days_remaining()
            if days is None:
                return f"👑 {tier_name} • Lifetime Active"
            return f"👑 {tier_name} • {days} Days Remaining"
        remaining = self.get_daily_trial_remaining()
        return f"⏳ Trial Mode • {remaining}/{DAILY_TRIAL_LIMIT} Downloads Left Today"

    def activate_key(self, key: str) -> tuple[bool, str]:
        """Activates a license key on the current machine."""
        is_valid, tier, err = verify_license_key(key, self.machine_id)
        if not is_valid:
            return False, err or "Invalid license key."

        now = datetime.now().date()
        days = TIER_DAYS.get(tier)
        expiry_str = ""
        if days is not None:
            exp_date = now + timedelta(days=days)
            expiry_str = exp_date.strftime("%Y-%m-%d")

        self.license_data = LicenseData(
            key=key.strip().upper(),
            tier=tier,
            activated_date=now.strftime("%Y-%m-%d"),
            expiry_date=expiry_str,
            bound_hwid=self.machine_id,
            is_active=True,
        )
        self._save_license()
        tier_label = TIER_NAMES.get(tier, "Pro Edition")
        return True, f"Successfully activated {tier_label}! Unlimited downloads unlocked."

    def deactivate_key(self) -> None:
        """Removes activation from current computer."""
        self.license_data = LicenseData()
        self._save_license()

    # -------------------------------------------------------------------------
    # Daily Trial Tracking (5 Downloads Per Day)
    # -------------------------------------------------------------------------

    def _get_today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _clean_trial_record(self) -> None:
        """Resets trial count if date has changed (midnight reset)."""
        today = self._get_today_str()
        try:
            if self.trial_file.is_file():
                data = json.loads(self.trial_file.read_text(encoding="utf-8"))
                if data.get("date") != today:
                    self._write_trial_record(today, 0)
            else:
                self._write_trial_record(today, 0)
        except Exception:
            self._write_trial_record(today, 0)

    def _write_trial_record(self, date_str: str, count: int) -> None:
        try:
            self.appdata_dir.mkdir(parents=True, exist_ok=True)
            self.trial_file.write_text(json.dumps({"date": date_str, "count": count}), encoding="utf-8")
        except Exception:
            pass

    def get_daily_downloads_used(self) -> int:
        self._clean_trial_record()
        try:
            if self.trial_file.is_file():
                data = json.loads(self.trial_file.read_text(encoding="utf-8"))
                return int(data.get("count", 0))
        except Exception:
            pass
        return 0

    def get_daily_trial_remaining(self) -> int:
        if self.is_pro():
            return 999999
        used = self.get_daily_downloads_used()
        return max(0, DAILY_TRIAL_LIMIT - used)

    def can_download(self, requested_count: int = 1) -> tuple[bool, str]:
        """Checks if a download of requested_count items is permitted."""
        if self.is_pro():
            return True, "Pro Unlimited"
        remaining = self.get_daily_trial_remaining()
        if remaining >= requested_count:
            return True, f"{remaining} downloads remaining today"
        return False, f"Daily limit reached. You have {remaining} downloads left today (Max {DAILY_TRIAL_LIMIT}/day)."

    def record_downloads(self, count: int = 1) -> None:
        """Records completed/queued downloads towards the daily limit for trial users."""
        if self.is_pro():
            return
        used = self.get_daily_downloads_used()
        today = self._get_today_str()
        self._write_trial_record(today, used + count)


license_mgr = LicenseManager.get_instance()
