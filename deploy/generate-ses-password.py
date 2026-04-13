#!/usr/bin/env python3
"""
AWS SES SMTP password generator.
AWS SES SMTP passwords are NOT your IAM secret key directly.
They are derived using HMAC-SHA256 signing.

Usage:
  python3 generate-ses-password.py <IAM_SECRET_ACCESS_KEY> <AWS_REGION>

Example:
  python3 generate-ses-password.py "yourSecretKey" "us-east-1"
"""
import hmac
import hashlib
import base64
import sys

def generate_ses_smtp_password(secret_key: str, region: str) -> str:
    # AWS SES SMTP password derivation
    date      = "11111111"
    service   = "ses"
    terminal  = "aws4_request"
    message   = "SendRawEmail"
    version   = 0x04

    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    sig = sign(
        sign(
            sign(
                sign(
                    sign(("AWS4" + secret_key).encode("utf-8"), date),
                    region,
                ),
                service,
            ),
            terminal,
        ),
        message,
    )
    sig_with_version = bytes([version]) + sig
    return base64.b64encode(sig_with_version).decode("utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    secret = sys.argv[1]
    region = sys.argv[2]
    smtp_pass = generate_ses_smtp_password(secret, region)
    print(f"\nSES SMTP Password for region {region}:")
    print(smtp_pass)
    print("\nUpdate your .env:")
    print(f"EMAIL_SMTP_PASS={smtp_pass}")
