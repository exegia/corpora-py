"""generate_unique_id and self-signed cert generation."""

from types import SimpleNamespace

import pytest

from common.utils import helpers


def test_generate_unique_id_uses_first_tag_and_name():
    route = SimpleNamespace(tags=["convert"], name="upload")
    assert helpers.generate_unique_id(route) == "convert-upload"


@pytest.mark.xfail(
    reason=(
        "generate_ssl_cert is broken under pyOpenSSL >= 25: X509.add_extensions "
        "was removed (deprecated API). The function is also unused anywhere in "
        "the repo -- fix by porting to cryptography's CertificateBuilder, or "
        "delete as dead code."
    ),
    raises=AttributeError,
    strict=True,
)
def test_generate_ssl_cert_writes_valid_pem_pair(tmp_path, monkeypatch):
    cert_dir = tmp_path / "certs"
    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"
    monkeypatch.setattr(helpers, "CERT_DIR", cert_dir)
    monkeypatch.setattr(helpers, "CERT_FILE", cert_file)
    monkeypatch.setattr(helpers, "KEY_FILE", key_file)

    returned_cert, returned_key = helpers.generate_ssl_cert()

    assert returned_cert == cert_file and returned_key == key_file
    assert b"BEGIN CERTIFICATE" in cert_file.read_bytes()
    assert b"PRIVATE KEY" in key_file.read_bytes()
