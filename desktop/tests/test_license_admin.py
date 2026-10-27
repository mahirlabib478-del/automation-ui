from __future__ import annotations

import argparse
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from desktop.licensing.license_core import validate_license_key
from tools.license_admin import generate_keys, issue_license


class LicenseAdminTests(unittest.TestCase):
    def test_generate_and_issue_license_round_trip(self) -> None:
        machine_id = "0123456789ABCDEF0123456789ABCDEF"
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            private_key = base / "seller" / "private.pem"
            public_module = base / "app" / "license_public_key.py"
            license_file = base / "issued" / "customer-license.txt"

            generate_args = argparse.Namespace(
                private_key_out=str(private_key),
                public_module_out=str(public_module),
                force=False,
            )
            with patch("tools.license_admin._passphrase", return_value="example passphrase 123"):
                self.assertEqual(generate_keys(generate_args), 0)

            match = re.search(r'PUBLIC_KEY_B64 = "([^"]+)"', public_module.read_text(encoding="utf-8"))
            self.assertIsNotNone(match)
            public_key_b64 = match.group(1)

            issue_args = argparse.Namespace(
                private_key=str(private_key),
                machine_id=machine_id,
                customer="Test Customer",
                license_id="AFS-ROUNDTRIP-01",
                expires=None,
                output=str(license_file),
            )
            with patch("tools.license_admin.getpass.getpass", return_value="example passphrase 123"):
                self.assertEqual(issue_license(issue_args), 0)

            token = license_file.read_text(encoding="utf-8").strip()
            result = validate_license_key(
                token,
                machine_id=machine_id,
                now=datetime.now(timezone.utc),
                public_key_b64=public_key_b64,
            )
            self.assertTrue(result.valid, result.message)
            self.assertEqual(result.payload["customer"], "Test Customer")
            self.assertEqual(result.payload["license_id"], "AFS-ROUNDTRIP-01")
            self.assertFalse(private_key.read_text(encoding="utf-8").startswith("-----BEGIN PRIVATE KEY-----"))


if __name__ == "__main__":
    unittest.main()
