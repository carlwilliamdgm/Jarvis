"""Windows Hello credential registry and WebAuthn ceremony coordinator.

Credential public keys are stored DPAPI protected per Windows user. The
private authenticator key remains managed by Windows Hello and is never read
by GreatOS.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from datashield.webauthn_auth import WebAuthnCeremonies, WebAuthnError
from datashield.windows_key_store import key_store_path, protect_secret, unprotect_secret


_LOCK = threading.RLock()
_CEREMONIES = WebAuthnCeremonies(capacity=256, ttl_seconds=180)


def _credentials_path() -> Path:
    return key_store_path().with_name("hello-credentials.dpapi")


def _load_credentials() -> dict[str, dict[str, Any]]:
    path = _credentials_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(unprotect_secret(path))
    except Exception as exc:
        raise RuntimeError("Le registre Windows Hello est illisible ou invalide.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Le registre Windows Hello a un format invalide.")
    return data


def _save_credentials(data: dict[str, dict[str, Any]]) -> None:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    protect_secret(encoded, _credentials_path())


def origin_and_rp_id(origin: str) -> tuple[str, str]:
    if not isinstance(origin, str) or origin != origin.strip():
        raise WebAuthnError("Origine WebAuthn absente ou invalide.")
    parsed = urlsplit(origin)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise WebAuthnError("Une origine exacte est requise.")
    host = parsed.hostname.lower().rstrip(".")
    if parsed.scheme != "https" and host not in ("localhost", "127.0.0.1", "::1"):
        raise WebAuthnError("HTTPS est requis hors boucle locale.")
    return origin, host


def begin_registration(origin: str, *, require_prf: bool = True) -> dict[str, Any]:
    exact_origin, rp_id = origin_and_rp_id(origin)
    if rp_id in ("127.0.0.1", "::1"):
        raise WebAuthnError("Windows Hello PRF requiert l’origine http://localhost, pas une adresse IP locale.")
    with _LOCK:
        if exact_origin in _load_credentials():
            raise WebAuthnError("Un authentificateur existe déjà pour cette origine; le remplacement est refusé.")
    return _CEREMONIES.create_registration_options(
        rp_id=rp_id, rp_name="GreatOS", user_id=b"greatos-local-user",
        user_name="GreatOS local profile", origins=[exact_origin], enable_prf=require_prf,
    )


def finish_registration(origin: str, ceremony_id: str, credential: dict[str, Any], *,
                        require_prf: bool = True) -> None:
    exact_origin, _ = origin_and_rp_id(origin)
    with _LOCK:
        if exact_origin in _load_credentials():
            raise WebAuthnError("Un authentificateur existe déjà pour cette origine; le remplacement est refusé.")
    verified = _CEREMONIES.verify_registration(ceremony_id=ceremony_id, credential=credential, origin=exact_origin)
    extensions = credential.get("clientExtensionResults")
    prf_result = extensions.get("prf") if isinstance(extensions, dict) else None
    prf_enabled = isinstance(prf_result, dict) and prf_result.get("enabled") is True
    if require_prf and not prf_enabled:
        raise WebAuthnError("Cet authentificateur Windows Hello ne prend pas en charge PRF.")
    item = {
        "credential_id": base64.b64encode(verified.credential_id).decode("ascii"),
        "public_key": base64.b64encode(verified.public_key).decode("ascii"),
        "sign_count": verified.sign_count,
        # Stable salt for this credential's DataShield key envelope.
        "prf_salt": base64.b64encode(secrets.token_bytes(32)).decode("ascii") if prf_enabled else None,
        "prf_enabled": prf_enabled,
    }
    with _LOCK:
        registry = _load_credentials()
        if exact_origin in registry:
            raise WebAuthnError("Un authentificateur existe déjà pour cette origine; le remplacement est refusé.")
        registry[exact_origin] = item
        _save_credentials(registry)


def has_credential(origin: str) -> bool:
    exact_origin, _ = origin_and_rp_id(origin)
    with _LOCK:
        return exact_origin in _load_credentials()


def has_prf_credential(origin: str) -> bool:
    exact_origin, _ = origin_and_rp_id(origin)
    with _LOCK:
        item = _load_credentials().get(exact_origin)
    return bool(item and item.get("prf_enabled") is True and item.get("prf_salt"))


def begin_authentication(origin: str) -> dict[str, Any]:
    exact_origin, rp_id = origin_and_rp_id(origin)
    with _LOCK:
        item = _load_credentials().get(exact_origin)
    if not item:
        raise WebAuthnError("Aucun authentificateur Windows Hello n’est enrôlé pour cette origine.")
    credential_id = base64.b64decode(item["credential_id"], validate=True)
    options = _CEREMONIES.create_authentication_options(
        rp_id=rp_id, origins=[exact_origin], credential_ids=[credential_id],
    )
    return options


def begin_key_unlock(origin: str) -> dict[str, Any]:
    """Start a Hello assertion with the stable PRF salt for local key unwrap."""
    exact_origin, rp_id = origin_and_rp_id(origin)
    if rp_id in ("127.0.0.1", "::1"):
        raise WebAuthnError("Windows Hello PRF requiert l’origine http://localhost, pas une adresse IP locale.")
    with _LOCK:
        item = _load_credentials().get(exact_origin)
    if not item or item.get("prf_enabled") is not True or not item.get("prf_salt"):
        raise WebAuthnError("Windows Hello doit être réenrôlé avec prise en charge PRF.")
    salt = base64.b64decode(item["prf_salt"], validate=True)
    if len(salt) != 32:
        raise WebAuthnError("Le sel PRF Windows Hello est invalide.")
    credential_id = base64.b64decode(item["credential_id"], validate=True)
    options = _CEREMONIES.create_authentication_options(
        rp_id=rp_id, origins=[exact_origin], credential_ids=[credential_id], prf_salt=salt,
    )
    return options


def finish_authentication(origin: str, ceremony_id: str, credential: dict[str, Any]) -> bool:
    exact_origin, _ = origin_and_rp_id(origin)
    with _LOCK:
        registry = _load_credentials()
        item = registry.get(exact_origin)
        if not item:
            raise WebAuthnError("Aucun authentificateur enrôlé pour cette origine.")
        credential_id = base64.b64decode(item["credential_id"], validate=True)
        public_key = base64.b64decode(item["public_key"], validate=True)
        result = _CEREMONIES.verify_authentication(
            ceremony_id=ceremony_id, credential_id=credential_id, credential=credential,
            public_key=public_key, sign_count=int(item["sign_count"]), origin=exact_origin,
        )
        if result.new_sign_count:
            item["sign_count"] = result.new_sign_count
            _save_credentials(registry)
    return True


def finish_prf_authentication(origin: str, ceremony_id: str,
                              credential: dict[str, Any]) -> bytes:
    """Verify the assertion and return its registered PRF salt atomically.

    The client never chooses the salt used to wrap DataShield. It is read from
    the same protected registry entry whose credential just verified.
    """
    exact_origin, _ = origin_and_rp_id(origin)
    with _LOCK:
        registry = _load_credentials()
        item = registry.get(exact_origin)
        if not item or item.get("prf_enabled") is not True:
            raise WebAuthnError("Aucun credential PRF Windows Hello n’est enrôlé pour cette origine.")
        try:
            credential_id = base64.b64decode(item["credential_id"], validate=True)
            public_key = base64.b64decode(item["public_key"], validate=True)
            prf_salt = base64.b64decode(item["prf_salt"], validate=True)
            sign_count = int(item["sign_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WebAuthnError("Les métadonnées du credential PRF sont invalides.") from exc
        if len(prf_salt) != 32:
            raise WebAuthnError("Le sel PRF enregistré est invalide.")
        result = _CEREMONIES.verify_authentication(
            ceremony_id=ceremony_id, credential_id=credential_id, credential=credential,
            public_key=public_key, sign_count=sign_count, origin=exact_origin,
        )
        if result.new_sign_count:
            item["sign_count"] = result.new_sign_count
            _save_credentials(registry)
        return prf_salt
