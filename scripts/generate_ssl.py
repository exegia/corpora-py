"""
Generate a self-signed SSL certificate on every app start.
Cert and key are written to app/ relative to the working directory
"""

import logging
from pathlib import Path

from OpenSSL import crypto

logger = logging.getLogger(__name__)

CERT_DIR = Path("src/exegia/supabase")
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def generate_ssl_cert() -> tuple[Path, Path]:
    """Generate a self-signed certificate and write it to .venv/.

    Returns the (cert_path, key_path) tuple.
    Overwrites any existing files so the cert is always fresh on startup.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Key pair ──────────────────────────────────────────────────────────────
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)

    # ── Certificate ───────────────────────────────────────────────────────────
    cert = crypto.X509()
    cert.get_subject().C = "US"
    cert.get_subject().ST = "Local"
    cert.get_subject().L = "Local"
    cert.get_subject().O = "Exegia"
    cert.get_subject().OU = "Dev"
    cert.get_subject().CN = "localhost"

    cert.set_serial_number(1)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)  # valid for 1 year
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)

    # SAN extension so browsers/clients accept the cert for localhost
    cert.add_extensions(
        [
            crypto.X509Extension(
                b"subjectAltName", False, b"DNS:localhost,IP:127.0.0.1"
            ),
            crypto.X509Extension(b"basicConstraints", True, b"CA:TRUE"),
        ]
    )

    cert.sign(key, "sha256")

    # ── Write PEM files ───────────────────────────────────────────────────────
    CERT_FILE.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    KEY_FILE.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))

    logger.info("SSL certificate written to %s / %s", CERT_FILE, KEY_FILE)
    return CERT_FILE, KEY_FILE
