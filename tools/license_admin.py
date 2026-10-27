#!/usr/bin/env python3
"""Offline license administration for ADB Flow Studio.

Generate the signing keypair on a trusted PC. Keep the private key and its
passphrase offline and outside the application repository.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.licensing.license_core import (
    PRODUCT_ID,
    create_license_token,
    normalize_machine_id,
)


DEFAULT_PRIVATE_KEY = Path.home() / "Documents" / "ADB Flow Studio Admin" / "license_private_key.pem"
DEFAULT_PUBLIC_MODULE = ROOT / "desktop" / "licensing" / "license_public_key.py"


def _passphrase(confirm: bool = False) -> str:
    value = getpass.getpass("Private-key passphrase: ")
    if len(value) < 12:
        raise ValueError("Use a passphrase of at least 12 characters.")
    if confirm:
        again = getpass.getpass("Repeat passphrase: ")
        if value != again:
            raise ValueError("Passphrases do not match.")
    return value


def generate_keys(args: argparse.Namespace) -> int:
    private_path = Path(args.private_key_out).expanduser().resolve()
    public_path = Path(args.public_module_out).expanduser().resolve()
    if ROOT == private_path or ROOT in private_path.parents:
        raise ValueError("The private key must be stored outside the repository.")
    if (private_path.exists() or public_path.exists()) and not args.force:
        raise FileExistsError("A key file already exists. Use --force only if you intend to replace it.")
    passphrase = _passphrase(confirm=True)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private_bytes)
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    public_b64 = base64.b64encode(public_bytes).decode("ascii")
    public_path.write_text(
        '"""Public Ed25519 key embedded in ADB Flow Studio. Safe to distribute."""\n'
        f'PUBLIC_KEY_B64 = "{public_b64}"\n',
        encoding="utf-8",
    )
    print(f"Private signing key saved outside the repository: {private_path}")
    print(f"Public key module created: {public_path}")
    print("Keep the private key and passphrase backed up and offline. Never commit the private key.")
    print("The public key module may be committed and is embedded in the next application build.")
    return 0


def issue_license(args: argparse.Namespace) -> int:
    private_path = Path(args.private_key).expanduser()
    if not private_path.is_file():
        raise FileNotFoundError(f"Private key file not found: {private_path}")
    passphrase = getpass.getpass("Private-key passphrase: ")
    private_key = serialization.load_pem_private_key(
        private_path.read_bytes(),
        password=passphrase.encode("utf-8"),
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("The selected private key is not an Ed25519 key.")

    machine_id = normalize_machine_id(args.machine_id)
    if len(machine_id) != 32:
        raise ValueError("Machine ID must contain exactly 32 hexadecimal characters.")
    if not args.customer.strip():
        raise ValueError("Customer name cannot be empty.")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    license_id = args.license_id.strip() if args.license_id else (
        "AFS-" + now.strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
    )
    expires_at = None
    license_type = "perpetual"
    if args.expires:
        expiry_date = date.fromisoformat(args.expires)
        if expiry_date < now.date():
            raise ValueError("Expiry date cannot be in the past.")
        expires_at = datetime.combine(
            expiry_date, time(23, 59, 59), tzinfo=timezone.utc
        ).isoformat().replace("+00:00", "Z")
        license_type = "subscription"

    payload = {
        "product": PRODUCT_ID,
        "license_id": license_id,
        "customer": args.customer.strip(),
        "machine_id": machine_id,
        "license_type": license_type,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
    }
    token = create_license_token(payload, private_key)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(token + "\n", encoding="utf-8")
        print(f"License key saved to: {output_path.resolve()}")
    else:
        print(token)
    print(f"License ID: {license_id}")
    print(f"Customer: {args.customer.strip()}")
    print(f"Machine ID: {format_machine_id_for_display(machine_id)}")
    print(f"Type: {license_type}")
    print(f"Expires: {expires_at or 'Never'}")
    return 0


def format_machine_id_for_display(value: str) -> str:
    return "-".join(value[index:index + 8] for index in range(0, len(value), 8))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and issue offline ADB Flow Studio licenses.")
    commands = parser.add_subparsers(dest="command", required=True)

    key_parser = commands.add_parser("generate-keys", help="Generate an encrypted Ed25519 signing keypair.")
    key_parser.add_argument("--private-key-out", default=str(DEFAULT_PRIVATE_KEY))
    key_parser.add_argument("--public-module-out", default=str(DEFAULT_PUBLIC_MODULE))
    key_parser.add_argument("--force", action="store_true", help="Replace existing key files.")
    key_parser.set_defaults(handler=generate_keys)

    issue_parser = commands.add_parser("issue", help="Issue a signed license for one PC.")
    issue_parser.add_argument("--private-key", required=True)
    issue_parser.add_argument("--machine-id", required=True)
    issue_parser.add_argument("--customer", required=True)
    issue_parser.add_argument("--license-id")
    issue_parser.add_argument("--expires", help="Optional expiry date in YYYY-MM-DD format; omit for perpetual.")
    issue_parser.add_argument("--output", help="Optional file path to save the license key.")
    issue_parser.set_defaults(handler=issue_license)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
