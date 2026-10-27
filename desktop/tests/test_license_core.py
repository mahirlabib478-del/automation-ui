from __future__ import annotations

import base64
import unittest
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.licensing.license_core import (
    PRODUCT_ID,
    create_license_token,
    format_machine_id,
    normalize_machine_id,
    validate_license_key,
)


class LicenseCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.generate()
        raw_public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_b64 = base64.b64encode(raw_public_key).decode("ascii")
        self.machine_id = "0123456789ABCDEF0123456789ABCDEF"
        self.now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.payload = {
            "product": PRODUCT_ID,
            "license_id": "AFS-TEST-001",
            "customer": "Example Customer",
            "machine_id": self.machine_id,
            "license_type": "perpetual",
            "issued_at": "2026-10-27T11:00:00Z",
            "expires_at": None,
        }

    def test_valid_signed_license(self) -> None:
        token = create_license_token(self.payload, self.private_key)
        result = validate_license_key(
            token,
            machine_id=self.machine_id,
            now=self.now,
            public_key_b64=self.public_key_b64,
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.payload["license_id"], "AFS-TEST-001")

    def test_license_for_another_machine_is_rejected(self) -> None:
        token = create_license_token(self.payload, self.private_key)
        result = validate_license_key(
            token,
            machine_id="FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
            now=self.now,
            public_key_b64=self.public_key_b64,
        )
        self.assertFalse(result.valid)
        self.assertIn("different PC", result.message)

    def test_expired_license_is_rejected(self) -> None:
        payload = dict(self.payload)
        payload["expires_at"] = "2026-10-26T23:59:59Z"
        token = create_license_token(payload, self.private_key)
        result = validate_license_key(
            token,
            machine_id=self.machine_id,
            now=self.now,
            public_key_b64=self.public_key_b64,
        )
        self.assertFalse(result.valid)
        self.assertIn("expired", result.message)

    def test_tampered_signature_is_rejected(self) -> None:
        token = create_license_token(self.payload, self.private_key)
        prefix, payload_part, signature_part = token.split(".")
        changed = signature_part[:-1] + ("A" if signature_part[-1] != "A" else "B")
        result = validate_license_key(
            f"{prefix}.{payload_part}.{changed}",
            machine_id=self.machine_id,
            now=self.now,
            public_key_b64=self.public_key_b64,
        )
        self.assertFalse(result.valid)

    def test_bad_token_format_is_rejected(self) -> None:
        result = validate_license_key(
            "not-a-license",
            machine_id=self.machine_id,
            now=self.now,
            public_key_b64=self.public_key_b64,
        )
        self.assertFalse(result.valid)
        self.assertIn("format", result.message)

    def test_machine_id_formatting_and_normalization(self) -> None:
        formatted = format_machine_id(self.machine_id)
        self.assertEqual(formatted, "01234567-89ABCDEF-01234567-89ABCDEF")
        self.assertEqual(normalize_machine_id(formatted), self.machine_id)


if __name__ == "__main__":
    unittest.main()
