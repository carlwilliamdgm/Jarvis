# datashield/tools.py
"""Outils et façades publiques de capacités pour le module DataShield (GreatOS Module 6)."""

from __future__ import annotations

from datashield.defcon import DefconLevel, defcon
from datashield.error_classification import resultat_erreur
from datashield.crypto import crypto_engine


def obtenir_niveau_defcon() -> str:
    """Retourne le niveau DEFCON actuel et sa signification."""
    lvl = defcon.current_level
    descriptions = {
        5: "Nominal / standard",
        4: "Vigilance accrue",
        3: "Sécurisé (confirmation obligatoire pour commandes)",
        2: "Alerte haute (actions destructives bloquées)",
        1: "Confinement critique (verrouillage complet)",
    }
    desc = descriptions.get(lvl.value, "Inconnu")
    return f"Niveau DEFCON actuel : {lvl.name} ({lvl.value}) - {desc}"


def changer_niveau_defcon(niveau: int) -> str:
    """Modifie le niveau de sécurité DEFCON (1 à 5)."""
    try:
        val = int(niveau)
        if val not in {1, 2, 3, 4, 5}:
            return f"Niveau DEFCON invalide ({niveau}). Choisissez une valeur entre 1 et 5."
        nouveau = DefconLevel(val)
        defcon.set_level(nouveau)
        return f"Niveau DEFCON mis à jour avec succès : {nouveau.name} ({nouveau.value})"
    except Exception as e:
        return str(resultat_erreur(f"Erreur lors du changement DEFCON : {e}", e))


def statut_chiffrement() -> str:
    """Retourne l'état du moteur de chiffrement DataShield.

    Indique si AES-256-GCM est actif, si la bibliothèque est disponible et
    si la phrase secrète maître est configurée.
    """
    status = crypto_engine.status()
    if status["enabled"]:
        return (
            f"Chiffrement DataShield ACTIF — {status['algorithm']} "
            f"({status['key_size_bits']} bits), KDF : {status['kdf']} "
            f"({status['kdf_iterations']:,} itérations)."
        )
    if not status["library_available"]:
        return (
            "Chiffrement DataShield INACTIF — bibliothèque 'cryptography' non installée. "
            "Exécutez : pip install 'cryptography>=43.0.0,<45.0.0'"
        )
    return (
        "Chiffrement DataShield INACTIF — variable d'environnement 'JARVIS_CRYPTO_KEY' "
        "non définie. Définissez-la pour activer la protection AES-256-GCM."
    )


def chiffrer_valeur(valeur: str) -> str:
    """Chiffre une valeur textuelle avec AES-256-GCM.

    Retourne un blob base64 si le chiffrement est actif, sinon la valeur
    inchangée avec un avertissement.

    Args:
        valeur: Texte en clair à chiffrer.
    """
    if not crypto_engine.is_enabled:
        return f"[CHIFFREMENT INACTIF] {valeur}"
    try:
        return crypto_engine.encrypt(valeur)
    except Exception as e:
        return str(resultat_erreur(f"Échec du chiffrement : {e}", e))


def dechiffrer_valeur(blob: str) -> str:
    """Déchiffre un blob produit par ``chiffrer_valeur``.

    Retourne la valeur en clair. Si le chiffrement est inactif ou si le blob
    n'est pas reconnu, retourne le blob tel quel (compatibilité migration).

    Args:
        blob: Blob base64 chiffré ou valeur en clair.
    """
    if not crypto_engine.is_enabled:
        return blob
    try:
        return crypto_engine.decrypt(blob)
    except Exception as e:
        return str(resultat_erreur(f"Échec du déchiffrement : {e}", e))

