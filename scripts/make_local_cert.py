"""Self-signed certificate for trying the SSO login on a dev PC.

The IdP domain forces https (HSTS), so a hosts entry such as
``127.0.0.1 dtest-local.<idp domain>`` must be served over TLS:

    uv run --with cryptography python scripts/make_local_cert.py HOST

Writes .local/tls/HOST-key.pem and .local/tls/HOST-cert.pem (git-ignored).
Never use these outside the dev PC. scripts/run_local_https.ps1 calls this.
"""

import argparse
import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = Path(__file__).resolve().parents[1] / ".local" / "tls"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, args.host)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=args.days))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(args.host)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.host}-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    (OUT / f"{args.host}-cert.pem").write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
    )
    print(OUT / f"{args.host}-cert.pem")


if __name__ == "__main__":
    main()
