"""Provision production secrets without leaving the DataShield key in .env."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

racine = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(racine))

from datashield.env_loader import (  # noqa: E402
    charger_environnement,
    generer_secrets_production,
    preparer_cle_api_argon2,
    supprimer_cle_datashield,
)
from datashield.windows_key_store import (  # noqa: E402
    KeyStoreError,
    key_store_path,
    protect_secret,
    restore_secret_store,
    unprotect_secret,
)
from datashield.prf_key_envelope import envelope_path_for  # noqa: E402
from datashield.crypto import crypto_engine  # noqa: E402


def _remove_env_key(env_path: Path) -> None:
    """Remove every persisted DataShield master-key entry atomically-ish."""
    supprimer_cle_datashield(env_path)


def provision_datashield_key(env_path: Path) -> tuple[str, bool]:
    """Migrate/provision the per-user DPAPI key; return (key, was_new).

    Existing protected keys are immutable here. A legacy clear-text key is
    wrapped before its .env entry is removed. The key is returned only to the
    caller for the setup self-check and one-time manual recovery display.
    """
    if os.name != "nt":
        raise RuntimeError("Le provisioning DataShield nécessite Windows et DPAPI CurrentUser.")

    env_path = Path(env_path)
    store = key_store_path()
    configured_key = os.environ.get("JARVIS_CRYPTO_KEY")

    if envelope_path_for(store).is_file():
        raise RuntimeError(
            "Une clé DataShield est déjà liée à Windows Hello PRF. "
            "Le setup ne recrée pas de copie DPAPI; utilise le déverrouillage GreatOS ou la clé de secours."
        )

    if store.exists():
        protected_key = unprotect_secret(store)
        if configured_key and configured_key != protected_key:
            raise RuntimeError(
                "La clé .env/variable d'environnement diffère de la clé DPAPI existante; "
                "aucune clé ni donnée n'a été modifiée."
            )
        key = protected_key
        was_new = False
    else:
        key = configured_key or secrets.token_hex(32)
        protect_secret(key, store)
        # First DPAPI provisioning is a one-time opportunity to make a
        # manually entered recovery copy, whether migrated or freshly made.
        was_new = True

    # Persist a verifier independent of DPAPI before deleting any legacy
    # plaintext copy; a valid manual recovery key can rebuild a lost DPAPI blob.
    if not restore_secret_store(key, store):
        raise KeyStoreError("La clé DataShield ne peut pas être validée pour sa récupération.")

    _remove_env_key(env_path)
    os.environ.pop("JARVIS_CRYPTO_KEY", None)
    return key, was_new


def main() -> None:
    print("=" * 60)
    print("  GREATOS — INITIALISATION DE SÉCURITÉ PRODUCTION (DATASHIELD)")
    print("=" * 60)

    if os.name != "nt":
        print("[ERREUR] Ce setup de production requiert Windows et DPAPI CurrentUser.")
        sys.exit(1)

    env_path = racine / ".env"
    api_key_a_reveler = None
    if not env_path.exists():
        print("[+] Génération des secrets de production...")
        generated = generer_secrets_production(env_path)
        api_key_a_reveler = generated["JARVIS_API_KEY"]
        # If a protected master key already exists, do not compare it with the
        # temporary key emitted by the legacy generator.
        if key_store_path().exists():
            os.environ.pop("JARVIS_CRYPTO_KEY", None)
    else:
        print("[i] Fichier .env existant détecté.")
        charger_environnement(env_path)
        try:
            api_key_a_reveler = preparer_cle_api_argon2(env_path)
        except RuntimeError as exc:
            print(f"[ERREUR] Préparation du vérificateur Bearer Argon2id : {exc}")
            sys.exit(1)

    try:
        data_key, key_is_new = provision_datashield_key(env_path)
        # The key is opened only for this local self-check. At runtime DPAPI
        # CurrentUser unlocks automatically in the owning Windows session.
        crypto_engine.reload_passphrase()
        crypto_engine.unlock_with_manual_key(data_key)
        texte_test = "GreatOS: Test de chiffrement AES-256-GCM réussi."
        chiffre = crypto_engine.encrypt(texte_test)
        if crypto_engine.decrypt(chiffre) != texte_test:
            raise RuntimeError("Échec du test aller-retour DataShield.")
        crypto_engine.lock()
    except (KeyStoreError, RuntimeError) as exc:
        try:
            crypto_engine.lock()
        except Exception:
            pass
        print(f"[ERREUR] Provisioning DataShield impossible : {exc}")
        sys.exit(1)

    print(f"[OK] Clé DataShield protégée par DPAPI CurrentUser : {key_store_path()}")
    print("[OK] Vérification AES-256-GCM réussie; DataShield est reverrouillé.")
    recovery_marker = key_store_path().with_name("recovery-key-displayed")
    reveal_data_key = key_is_new or not recovery_marker.exists()
    if reveal_data_key:
        print("[!] Copiez la clé DataShield de secours dans votre gestionnaire de secrets :")
        print(f"    JARVIS_CRYPTO_KEY={data_key}")
        print("    Elle ne sera pas conservée en clair par GreatOS.")
        recovery_marker.parent.mkdir(parents=True, exist_ok=True)
        recovery_marker.write_text("displayed\n", encoding="ascii")
    if api_key_a_reveler:
        print("[!] Copiez maintenant la clé Bearer; elle ne sera plus conservée en clair :")
        print(f"    JARVIS_API_KEY={api_key_a_reveler}")
        print("    Gardez-la dans votre gestionnaire de secrets pour configurer les clients distants.")
    else:
        print("[OK] Vérificateur Argon2id Bearer configuré; aucun secret Bearer révélé.")
    print("=" * 60)


if __name__ == "__main__":
    main()
