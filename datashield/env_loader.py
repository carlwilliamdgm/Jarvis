"""Env Loader - Chargement automatique et sécurisé des variables d'environnement GreatOS.

Lit le fichier `.env` local sans dépendance externe lourde (ou via python-dotenv si présent)
au tout début du démarrage du système pour garantir l'activation de DataShield et des secrets.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import tempfile

from datashield.passwords import hacher_credential


def charger_environnement(chemin_env: Path | None = None) -> None:
    """Charge les variables clés depuis le fichier .env si présent."""
    env_file = chemin_env or (Path(__file__).resolve().parent.parent / ".env")
    if not env_file.exists():
        return

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                ligne = line.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, _, valeur = ligne.partition("=")
                cle = cle.strip()
                valeur = valeur.strip().strip("'\"")
                if cle and cle not in os.environ:
                    os.environ[cle] = valeur
    except Exception:
        pass


def generer_secrets_production(chemin_env: Path | None = None) -> dict[str, str]:
    """Génère les secrets et ne persiste que le vérificateur Argon2id du Bearer."""
    env_file = chemin_env or (Path(__file__).resolve().parent.parent / ".env")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    
    crypto_key = secrets.token_hex(32)  # 256 bits d'entropie cryptographique
    api_key = secrets.token_urlsafe(32)
    api_key_hash = hacher_credential(api_key)

    contenu = [
        "# === GREATOS PRODUCTION SECRETS (NE PAS COMMITER) ===",
        f"JARVIS_CRYPTO_KEY={crypto_key}",
        f"JARVIS_API_KEY_HASH={api_key_hash}",
        "GREATOS_ENV=production",
        "",
    ]

    _write_env_atomic(env_file, "\n".join(contenu))

    os.environ["JARVIS_CRYPTO_KEY"] = crypto_key
    os.environ["JARVIS_API_KEY_HASH"] = api_key_hash
    os.environ.pop("JARVIS_API_KEY", None)
    os.environ["GREATOS_ENV"] = "production"

    return {"JARVIS_CRYPTO_KEY": crypto_key, "JARVIS_API_KEY": api_key}


def _write_env_atomic(path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f"{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def supprimer_cle_datashield(chemin_env: Path | None = None) -> None:
    """Remove the persisted DataShield master key before enabling a Hello lock.

    The in-memory environment is cleared only after the file update is durable,
    so an I/O failure cannot silently leave the running process and disk in
    different recovery states.
    """
    env_file = chemin_env or (Path(__file__).resolve().parent.parent / ".env")
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        filtered = [line for line in lines if line.partition("=")[0].strip() != "JARVIS_CRYPTO_KEY"]
        if filtered != lines:
            _write_env_atomic(env_file, "\n".join(filtered).rstrip() + "\n")
        if any(line.partition("=")[0].strip() == "JARVIS_CRYPTO_KEY" for line in env_file.read_text(encoding="utf-8").splitlines()):
            raise RuntimeError("La copie locale de la clé DataShield n’a pas pu être retirée de .env.")
    os.environ.pop("JARVIS_CRYPTO_KEY", None)


def preparer_cle_api_argon2(chemin_env: Path | None = None) -> str | None:
    """Migrate or provision a Bearer verifier; return plaintext only for one-time display."""
    env_file = chemin_env or (Path(__file__).resolve().parent.parent / ".env")
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    api_key_entries: list[tuple[int, str]] = []
    hash_entries: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if key.strip() == "JARVIS_API_KEY":
            api_key_entries.append((index, value))
        elif key.strip() == "JARVIS_API_KEY_HASH":
            hash_entries.append((index, value))
    if len(api_key_entries) > 1 or len(hash_entries) > 1 or (api_key_entries and hash_entries):
        raise RuntimeError("Configuration Bearer ambiguë; aucun changement appliqué.")

    raw_key = api_key_entries[0][1] if api_key_entries else os.environ.get("JARVIS_API_KEY")
    existing_hash = hash_entries[0][1] if hash_entries else (
        os.environ.get("JARVIS_API_KEY_HASH") if not api_key_entries else None
    )
    if existing_hash:
        if not existing_hash.startswith("$argon2id$"):
            raise RuntimeError("Vérificateur Bearer non reconnu; aucun changement appliqué.")
        os.environ["JARVIS_API_KEY_HASH"] = existing_hash
        os.environ.pop("JARVIS_API_KEY", None)
        return None

    reveal_once = raw_key is None
    migrate_env_secret = bool(raw_key and not api_key_entries)
    if raw_key is None:
        raw_key = secrets.token_urlsafe(32)
    if not raw_key:
        raise RuntimeError("Clé Bearer vide; aucun changement appliqué.")
    verifier = hacher_credential(raw_key)

    if env_file.exists():
        if api_key_entries:
            lines[api_key_entries[0][0]] = f"JARVIS_API_KEY_HASH={verifier}"
        else:
            lines.append(f"JARVIS_API_KEY_HASH={verifier}")
        _write_env_atomic(env_file, "\n".join(lines) + "\n")
    os.environ["JARVIS_API_KEY_HASH"] = verifier
    os.environ.pop("JARVIS_API_KEY", None)
    return raw_key if reveal_once or api_key_entries or migrate_env_secret else None
