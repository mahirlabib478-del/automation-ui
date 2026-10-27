from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


PRODUCT_ID = "ADB-FLOW-STUDIO"
TOKEN_PREFIX = "AFS1"


try:
    from .license_public_key import PUBLIC_KEY_B64 as _EMBEDDED_PUBLIC_KEY_B64
except ImportError:
    _EMBEDDED_PUBLIC_KEY_B64 = ""


@dataclass(frozen=True)
class LicenseValidation:
    valid: bool
    message: str
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class LicenseStatus:
    machine_id: str
    enforcement_enabled: bool
    activated: bool
    message: str
    payload: dict[str, Any] | None = None


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def create_license_token(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Create a signed license token. Keep the private key outside the application."""
    payload_bytes = canonical_payload(payload)
    signature = private_key.sign(payload_bytes)
    return f"{TOKEN_PREFIX}.{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def normalize_machine_id(value: str) -> str:
    return "".join(character for character in str(value).upper() if character in "0123456789ABCDEF")


def format_machine_id(value: str) -> str:
    normalized = normalize_machine_id(value)
    return "-".join(normalized[index:index + 8] for index in range(0, len(normalized), 8))


def get_machine_id() -> str:
    """Create a stable, privacy-reduced machine identifier for offline activation."""
    material = ""
    if os.name == "nt":
        try:
            import winreg

            access = winreg.KEY_READ
            if hasattr(winreg, "KEY_WOW64_64KEY"):
                access |= winreg.KEY_WOW64_64KEY
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                access,
            ) as key:
                material = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except (OSError, ImportError, AttributeError):
            material = ""

    if not material:
        material = f"{platform.node()}|{uuid.getnode():012X}|{platform.system()}"
    digest = hashlib.sha256(f"{PRODUCT_ID}|machine-v1|{material}".encode("utf-8")).hexdigest()
    return digest[:32].upper()


def license_public_key_configured() -> bool:
    """True when a public-key constant was embedded at build time."""
    return bool(str(_EMBEDDED_PUBLIC_KEY_B64).strip())


def license_enforcement_enabled() -> bool:
    """Unconfigured source builds remain usable for development; configured builds enforce licensing."""
    return license_public_key_configured()


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("License date is missing.")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_license_key(
    token: str,
    machine_id: str | None = None,
    now: datetime | None = None,
    public_key_b64: str | None = None,
) -> LicenseValidation:
    """Verify the signature and license claims without using the network."""
    key_text = _EMBEDDED_PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
    if not str(key_text).strip():
        return LicenseValidation(False, "This developer build has no embedded license public key.")

    parts = str(token).strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return LicenseValidation(False, "License key format is invalid.")

    try:
        payload_bytes = _b64url_decode(parts[1])
        signature = _b64url_decode(parts[2])
        public_key_bytes = base64.b64decode(str(key_text), validate=True)
        if len(public_key_bytes) != 32:
            return LicenseValidation(False, "Embedded license public key is invalid.")
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, payload_bytes)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except InvalidSignature:
        return LicenseValidation(False, "License signature is invalid.")
    except (ValueError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        return LicenseValidation(False, f"License key could not be validated: {exc}")

    if not isinstance(payload, dict):
        return LicenseValidation(False, "License payload is invalid.")
    if payload.get("product") != PRODUCT_ID:
        return LicenseValidation(False, "This license was issued for a different product.")

    expected_machine = normalize_machine_id(machine_id or get_machine_id())
    licensed_machine = normalize_machine_id(str(payload.get("machine_id", "")))
    if len(expected_machine) != 32 or not hmac.compare_digest(expected_machine, licensed_machine):
        return LicenseValidation(False, "This license belongs to a different PC.")

    if not str(payload.get("license_id", "")).strip():
        return LicenseValidation(False, "License ID is missing.")
    if not str(payload.get("customer", "")).strip():
        return LicenseValidation(False, "Customer name is missing.")

    try:
        issued_at = _parse_datetime(payload.get("issued_at"))
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if issued_at > current_time.replace(microsecond=0) + timedelta(minutes=10):
            return LicenseValidation(False, "License issue time is in the future.")
        expires_at = payload.get("expires_at")
        if expires_at:
            expiry = _parse_datetime(expires_at)
            if current_time > expiry:
                return LicenseValidation(False, "License has expired.")
    except (ValueError, TypeError, OverflowError) as exc:
        return LicenseValidation(False, f"License date is invalid: {exc}")

    return LicenseValidation(True, "License is valid for this PC.", payload)


def license_storage_path() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.environ.get("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"]).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base / "ADBFlowStudio" / "license.json"


def load_stored_license() -> str:
    path = license_storage_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if isinstance(payload, dict):
        return str(payload.get("license_key", "")).strip()
    return ""


def save_stored_license(token: str) -> Path:
    path = license_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"license_key": token.strip()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def current_license_status() -> LicenseStatus:
    machine_id = get_machine_id()
    if not license_enforcement_enabled():
        return LicenseStatus(
            machine_id=machine_id,
            enforcement_enabled=False,
            activated=True,
            message="Developer mode: no embedded public signing key is configured.",
        )

    token = load_stored_license()
    if not token:
        return LicenseStatus(
            machine_id=machine_id,
            enforcement_enabled=True,
            activated=False,
            message="No license is activated on this PC.",
        )
    validation = validate_license_key(token, machine_id=machine_id)
    return LicenseStatus(
        machine_id=machine_id,
        enforcement_enabled=True,
        activated=validation.valid,
        message=validation.message,
        payload=validation.payload,
    )
