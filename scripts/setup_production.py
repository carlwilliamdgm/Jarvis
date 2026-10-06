"""Setup Production - Initialisation et vérification des clés de sécurité GreatOS."""

import sys
from pathlib import Path

# Ajouter la racine au path
racine = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(racine))

from datashield.env_loader import charger_environnement, generer_secrets_production
from datashield.crypto import crypto_engine


def main():
    print("=" * 60)
    print("  GREATOS — INITIALISATION DE SÉCURITÉ PRODUCTION (DATASHIELD)")
    print("=" * 60)

    env_path = racine / ".env"
    if not env_path.exists():
        print("[+] Génération d'un trousseau cryptographique sécurisé...")
        secrets_generes = generer_secrets_production(env_path)
        print(f"[OK] Fichier .env créé avec succès.")
        print(f"     Clé de chiffrement DataShield AES-256 : Définie (256 bits)")
        print(f"     Clé d'authentification API            : Définie (32 octets)")
    else:
        print("[i] Fichier .env existant détecté.")
        charger_environnement(env_path)

    # Recharger et tester le chiffrement
    crypto_engine.reload_passphrase()

    if not crypto_engine.is_enabled:
        print("[ERREUR] Le chiffrement DataShield n'a pas pu être activé.")
        sys.exit(1)

    # Test fonctionnel aller-retour
    texte_test = "GreatOS: Test de chiffrement AES-256-GCM réussi."
    chiffre = crypto_engine.encrypt(texte_test)
    dechiffre = crypto_engine.decrypt(chiffre)

    if dechiffre != texte_test:
        print("[ERREUR] Échec du test de déchiffrement DataShield !")
        sys.exit(1)

    print(f"[OK] Test cryptographique AES-256-GCM : VALIDÉ AVEC SUCCÈS")
    print("[OK] Protection des données et mémoires active pour la production.")
    print("=" * 60)


if __name__ == "__main__":
    main()
