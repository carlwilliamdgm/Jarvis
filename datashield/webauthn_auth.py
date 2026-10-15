"""Isolated WebAuthn ceremonies for Windows Hello / platform authenticators.

This module deliberately owns no HTTP routes or credential persistence. Callers
must persist verified credentials and supply their public key and counter for
authentication. Ceremony state is process-local, bounded, expiring, and one-shot.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


class WebAuthnError(ValueError):
    """Invalid ceremony input, configuration, or credential response."""


class CeremonyCapacityError(WebAuthnError):
    """The bounded pending ceremony table has no free slot."""


@dataclass(frozen=True)
class VerifiedCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    user_verified: bool


@dataclass(frozen=True)
class AuthenticationResult:
    credential_id: bytes
    new_sign_count: int
    user_verified: bool


@dataclass(frozen=True)
class _PendingCeremony:
    kind: str
    challenge: bytes
    rp_id: str
    origins: tuple[str, ...]
    expires_at: float
    user_id: bytes | None = None


def _validate_rp_origin(rp_id: str, origins: Iterable[str]) -> tuple[str, ...]:
    if not isinstance(rp_id, str) or not rp_id or rp_id != rp_id.strip():
        raise WebAuthnError("rp_id invalide.")
    rp = rp_id.lower().rstrip(".")
    labels = rp.split(".")
    if (":" in rp or "/" in rp or "*" in rp or " " in rp
            or any(not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels)):
        raise WebAuthnError("rp_id doit être un nom d’hôte, sans schéma ni chemin.")
    exact_origins = tuple(origins)
    if not exact_origins or len(set(exact_origins)) != len(exact_origins):
        raise WebAuthnError("Au moins une origine exacte et unique est requise.")
    for origin in exact_origins:
        if not isinstance(origin, str) or origin != origin.strip() or "*" in origin:
            raise WebAuthnError("Les origines doivent être exactes.")
        parsed = urlsplit(origin)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise WebAuthnError("Origine WebAuthn invalide.")
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise WebAuthnError("Une origine ne doit contenir que schéma, hôte et port.")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise WebAuthnError("HTTPS est requis hors boucle locale.")
        host = parsed.hostname.lower().rstrip(".")
        if host != rp and not host.endswith("." + rp):
            raise WebAuthnError("Le rp_id doit être l’hôte de l’origine ou un domaine parent.")
    return exact_origins


class WebAuthnCeremonies:
    """Create/verify WebAuthn options while enforcing ceremony lifecycle rules."""

    def __init__(
        self,
        *,
        capacity: int = 1024,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or ttl_seconds < 1:
            raise ValueError("capacity et ttl_seconds doivent être positifs.")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._pending: dict[str, _PendingCeremony] = {}
        self._lock = threading.Lock()

    def _new(self, kind: str, rp_id: str, origins: Iterable[str], user_id: bytes | None = None) -> tuple[str, bytes]:
        valid_origins = _validate_rp_origin(rp_id, origins)
        challenge = secrets.token_bytes(32)
        ceremony_id = secrets.token_urlsafe(32)
        now = self._clock()
        pending = _PendingCeremony(kind, challenge, rp_id.lower().rstrip("."), valid_origins, now + self._ttl, user_id)
        with self._lock:
            for key in [key for key, item in self._pending.items() if item.expires_at <= now]:
                del self._pending[key]
            if len(self._pending) >= self._capacity:
                raise CeremonyCapacityError("Trop de cérémonies WebAuthn en attente.")
            self._pending[ceremony_id] = pending
        return ceremony_id, challenge

    def _consume(self, ceremony_id: str, expected_kind: str) -> _PendingCeremony:
        now = self._clock()
        with self._lock:
            pending = self._pending.pop(ceremony_id, None)
        if pending is None or pending.kind != expected_kind or pending.expires_at <= now:
            raise WebAuthnError("Cérémonie inconnue, expirée ou déjà consommée.")
        return pending

    def create_registration_options(
        self, *, rp_id: str, rp_name: str, user_id: bytes, user_name: str,
        origins: Iterable[str], user_display_name: str | None = None,
        enable_prf: bool = False,
    ) -> dict:
        if not isinstance(user_id, bytes) or not user_id or len(user_id) > 64:
            raise WebAuthnError("user_id doit contenir entre 1 et 64 octets.")
        if not rp_name or not user_name:
            raise WebAuthnError("rp_name et user_name sont requis.")
        ceremony_id, challenge = self._new("registration", rp_id, origins, user_id)
        options = generate_registration_options(
            rp_id=rp_id.lower().rstrip("."), rp_name=rp_name, user_id=user_id,
            user_name=user_name, user_display_name=user_display_name or user_name,
            challenge=challenge,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        public_key = json.loads(options_to_json(options))
        if enable_prf:
            public_key["extensions"] = {"prf": {}}
        return {"ceremony_id": ceremony_id, "publicKey": public_key}

    def verify_registration(
        self, *, ceremony_id: str, credential: dict, origin: str | None = None,
    ) -> VerifiedCredential:
        pending = self._consume(ceremony_id, "registration")
        if origin is not None and origin not in pending.origins:
            raise WebAuthnError("L’origine de finalisation diffère de celle de la cérémonie.")
        try:
            verified = verify_registration_response(
                credential=credential, expected_challenge=pending.challenge,
                expected_rp_id=pending.rp_id, expected_origin=list(pending.origins),
                require_user_verification=True,
            )
        except Exception as exc:
            raise WebAuthnError("Réponse d’enrôlement WebAuthn invalide.") from exc
        if not verified.user_verified:
            raise WebAuthnError("La vérification utilisateur est requise.")
        return VerifiedCredential(
            credential_id=verified.credential_id, public_key=verified.credential_public_key,
            sign_count=verified.sign_count, aaguid=verified.aaguid,
            user_verified=verified.user_verified,
        )

    def create_authentication_options(
        self, *, rp_id: str, origins: Iterable[str], credential_ids: Iterable[bytes] | None = None,
        prf_salt: bytes | None = None,
    ) -> dict:
        descriptors = None
        if credential_ids is not None:
            ids = tuple(credential_ids)
            if not ids or any(not isinstance(item, bytes) or not item for item in ids):
                raise WebAuthnError("credential_ids doit contenir des identifiants binaires valides.")
            descriptors = [PublicKeyCredentialDescriptor(id=item) for item in ids]
        ceremony_id, challenge = self._new("authentication", rp_id, origins)
        options = generate_authentication_options(
            rp_id=rp_id.lower().rstrip("."), challenge=challenge,
            allow_credentials=descriptors,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        public_key = json.loads(options_to_json(options))
        if prf_salt is not None:
            if not isinstance(prf_salt, bytes) or len(prf_salt) != 32:
                raise WebAuthnError("Le sel PRF doit contenir exactement 32 octets.")
            # webauthn's JSON serializer does not expose the PRF extension yet.
            encoded_salt = base64.urlsafe_b64encode(prf_salt).rstrip(b"=").decode("ascii")
            public_key["extensions"] = {"prf": {"eval": {"first": encoded_salt}}}
        return {"ceremony_id": ceremony_id, "publicKey": public_key}

    def verify_authentication(
        self, *, ceremony_id: str, credential_id: bytes, credential: dict,
        public_key: bytes, sign_count: int, origin: str | None = None,
    ) -> AuthenticationResult:
        pending = self._consume(ceremony_id, "authentication")
        if origin is not None and origin not in pending.origins:
            raise WebAuthnError("L’origine de finalisation diffère de celle de la cérémonie.")
        if not isinstance(credential_id, bytes) or not isinstance(public_key, bytes) or sign_count < 0:
            raise WebAuthnError("Métadonnées de credential invalides.")
        try:
            verified = verify_authentication_response(
                credential=credential, expected_challenge=pending.challenge,
                expected_rp_id=pending.rp_id, expected_origin=list(pending.origins),
                credential_public_key=public_key,
                credential_current_sign_count=sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            raise WebAuthnError("Assertion WebAuthn invalide.") from exc
        if verified.credential_id != credential_id:
            raise WebAuthnError("Credential inattendue.")
        if not verified.user_verified:
            raise WebAuthnError("La vérification utilisateur est requise.")
        return AuthenticationResult(verified.credential_id, verified.new_sign_count, verified.user_verified)
