
import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.routing import APIRoute

from .console import corpora_logger
from .constant import CERT_DIR, CERT_FILE, KEY_FILE


def generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"

"""
Generate a self-signed SSL certificate on every app start.
Cert and key are written to app/ relative to the working directory
"""


def generate_ssl_cert() -> tuple[Path, Path]:
    """Generate a self-signed certificate and write it to .venv/.

    Returns the (cert_path, key_path) tuple.
    Overwrites any existing files so the cert is always fresh on startup.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Key pair ──────────────────────────────────────────────────────────────
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # ── Certificate ───────────────────────────────────────────────────────────
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Exegia"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Dev"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))  # valid for 1 year
        # SAN extension so browsers/clients accept the cert for localhost
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    # ── Write PEM files ───────────────────────────────────────────────────────
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    corpora_logger.info("SSL certificate written to %s / %s", CERT_FILE, KEY_FILE)
    return CERT_FILE, KEY_FILE
