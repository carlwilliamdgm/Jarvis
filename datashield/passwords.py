"""Argon2id helpers for verifiers of password-like credentials."""

from __future__ import annotations


def _password_hasher():
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:
        raise RuntimeError("Argon2id indisponible; installez les dépendances GreatOS.") from exc
    return PasswordHasher()


def hacher_credential(secret: str) -> str:
    """Create a PHC Argon2id verifier using the library's configured defaults."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("La credential à hacher doit être une chaîne non vide.")
    return _password_hasher().hash(secret)


def verifier_credential(secret: str, verifier: str) -> bool:
    """Verify a supplied credential against an Argon2id PHC verifier."""
    if not isinstance(secret, str) or not isinstance(verifier, str) or not verifier.startswith("$argon2id$"):
        raise ValueError("Vérificateur Argon2id invalide.")
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    try:
        return bool(_password_hasher().verify(verifier, secret))
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError) as exc:
        raise RuntimeError("Vérificateur Argon2id illisible.") from exc
