"""Env Loader - Chargement automatique et sécurisé des variables d'environnement GreatOS.

Lit le fichier `.env` local sans dépendance externe lourde (ou via python-dotenv si présent)
au tout début du démarrage du système pour garantir l'activation de DataShield et des secrets.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets


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
    """Génère un trousseau de clés cryptographiques fortes pour la production."""
    env_file = chemin_env or (Path(__file__).resolve().parent.parent / ".env")
    
    crypto_key = secrets.token_hex(32)  # 256 bits d'entropie cryptographique
    api_key = secrets.token_urlsafe(32)

    contenu = [
        "# === GREATOS PRODUCTION SECRETS (NE PAS COMMITER) ===",
        f"JARVIS_CRYPTO_KEY={crypto_key}",
        f"JARVIS_API_KEY={api_key}",
        "GREATOS_ENV=production",
        "",
    ]

    with open(env_file, "w", encoding="utf-8") as f:
        f.write("\n".join(contenu))

    # Recharger dans l'environnement courant
    os.environ["JARVIS_CRYPTO_KEY"] = crypto_key
    os.environ["JARVIS_API_KEY"] = api_key
    os.environ["GREATOS_ENV"] = "production"

    return {"JARVIS_CRYPTO_KEY": crypto_key, "JARVIS_API_KEY": api_key}
