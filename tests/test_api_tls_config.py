"""Fail-closed operator TLS configuration for the Windows API listener."""

import ssl
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from interface_morphique import server


def test_non_loopback_listener_requires_operator_certificate(monkeypatch):
    monkeypatch.delenv("GREATOS_TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("GREATOS_TLS_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError, match="Écoute réseau refusée sans certificat TLS opérateur"):
        server.serve_api("0.0.0.0", 8000)


def test_non_loopback_listener_requires_a_remote_certificate_identity(monkeypatch, tmp_path):
    cert = tmp_path / "operator.crt"
    key = tmp_path / "operator.key"
    cert.write_text("placeholder", encoding="ascii")
    key.write_text("placeholder", encoding="ascii")
    monkeypatch.setenv("GREATOS_TLS_CERT_FILE", str(cert))
    monkeypatch.setenv("GREATOS_TLS_KEY_FILE", str(key))
    monkeypatch.delenv("GREATOS_TLS_SERVER_NAME", raising=False)

    with pytest.raises(RuntimeError, match="GREATOS_TLS_SERVER_NAME"):
        server.serve_api("0.0.0.0", 8000)


def test_tls_configuration_requires_certificate_and_private_key_pair(monkeypatch, tmp_path):
    cert = tmp_path / "operator.crt"
    cert.write_text("placeholder", encoding="ascii")
    monkeypatch.setenv("GREATOS_TLS_CERT_FILE", str(cert))
    monkeypatch.delenv("GREATOS_TLS_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError, match="doivent être configurés ensemble"):
        server.serve_api("127.0.0.1", 8000)


def test_loopback_listener_remains_available_without_operator_tls(monkeypatch):
    monkeypatch.delenv("GREATOS_TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("GREATOS_TLS_KEY_FILE", raising=False)

    assert server._is_loopback_bind("127.0.0.1")
    assert server._is_loopback_bind("::1")
    assert server._is_loopback_bind("localhost")
    assert not server._is_loopback_bind("0.0.0.0")
    assert not server._is_loopback_bind("192.0.2.20")


def test_operator_tls_context_enforces_tls_1_3():
    context = server.enforce_tls_1_3(ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER))

    assert context.minimum_version is ssl.TLSVersion.TLSv1_3


def test_operator_certificate_requires_matching_key_and_client_sans(tmp_path):
    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GreatOS test")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"), x509.DNSName("greatos.example.test"),
            x509.IPAddress(ip_address("192.0.2.20")),
        ]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))

    names = server.validate_operator_tls_files(str(cert_path), str(key_path), "greatos.example.test")
    assert "localhost" in names
    assert "192.0.2.20" in names
    with pytest.raises(RuntimeError, match="SAN du certificat TLS"):
        server.validate_operator_tls_files(str(cert_path), str(key_path), "wrong.example.test")

