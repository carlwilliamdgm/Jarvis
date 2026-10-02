#context_engine/trust_registry.py

"""
Registre d'Autonomie Progressive (Trust Matrix) - Jalon 5.

Ce module gère les niveaux d'autonomie de Jarvis par domaine d'action et par utilisateur.
Le système utilise un mécanisme à cliquet (ratchet) : promotion après N succès consécutifs,
rétrogradation immédiate après un échec.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from context_engine.paths import JARVIS_DIR
from context_engine.user_profile import resoudre_utilisateur_actif


# Chemin du dossier des profils
PROFILES_DIR = JARVIS_DIR / "learning" / "profiles"

# Seuil de succès consécutifs pour la promotion
SEUIL_PROMOTION = 5

# Les 4 niveaux d'autonomie
NIVEAU_OBSERVATION = 0  # Confirmation stricte avant chaque exécution
NIVEAU_PROPOSITION = 1  # Proposition motivée avec explication
NIVEAU_ACTION_NOTIFICATION = 2  # Exécution directe avec notification
NIVEAU_AUTONOMIE_SILENCIEUSE = 3  # Exécution sans déranger


def extraire_domaine_capacite(capacite: str) -> str:
    """
    Extrait le domaine à partir du nom de la capacité.
    
    Transforme les capacités en noms de domaines normalisés :
    - "fichiers.lire" → "fichiers_lecture"
    - "fichiers.ecrire" → "fichiers_ecriture"
    - "systeme.commande" → "commandes_systeme"
    - "web.recherche" → "web_recherche"
    
    Args:
        capacite: Le nom de la capacité (ex: "fichiers.lire").
        
    Returns:
        Le domaine normalisé (ex: "fichiers_lecture").
    """
    if not capacite:
        return "inconnu"
    
    # Remplacer les points par des underscores
    domaine = capacite.replace(".", "_")
    
    # Nettoyer les caractères spéciaux
    domaine = re.sub(r"[^\w]", "_", domaine)
    
    # Normaliser les underscores multiples
    domaine = re.sub(r"_+", "_", domaine)
    
    # Enlever les underscores au début et à la fin
    domaine = domaine.strip("_")
    
    return domaine if domaine else "inconnu"


def _chemin_trust_matrix(user_id: str) -> Path:
    """
    Retourne le chemin du fichier trust_matrix.json pour un utilisateur donné.
    
    Args:
        user_id: L'identifiant utilisateur normalisé.
        
    Returns:
        Le chemin complet vers le fichier de matrice de confiance.
    """
    return PROFILES_DIR / user_id / "trust_matrix.json"


def _domaine_par_defaut() -> dict:
    """
    Génère un domaine par défaut avec niveau 0.
    
    Returns:
        Un dictionnaire de domaine initialisé avec des valeurs par défaut.
    """
    return {
        "niveau": NIVEAU_OBSERVATION,
        "score": 0.0,
        "succes_consecutifs": 0,
        "actions_totales": 0,
        "echecs": 0,
    }


def _charger_trust_matrix(user_id: str) -> dict:
    """
    Charge la matrice de confiance d'un utilisateur depuis le disque.
    
    Si le fichier n'existe pas, crée une matrice vide.
    
    Args:
        user_id: L'identifiant utilisateur normalisé.
        
    Returns:
        Le dictionnaire de la matrice de confiance.
    """
    chemin = _chemin_trust_matrix(user_id)
    
    # Créer le dossier parent s'il n'existe pas
    chemin.parent.mkdir(parents=True, exist_ok=True)
    
    # Charger la matrice si elle existe
    if chemin.exists():
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # En cas d'erreur, recréer la matrice
            pass
    
    # Créer une nouvelle matrice vide
    return {"domaines": {}}


def _sauvegarder_trust_matrix(matrix: dict, user_id: str) -> None:
    """
    Sauvegarde la matrice de confiance d'un utilisateur sur le disque.
    
    Args:
        matrix: Le dictionnaire de la matrice à sauvegarder.
        user_id: L'identifiant utilisateur normalisé.
    """
    chemin = _chemin_trust_matrix(user_id)
    
    # Créer le dossier parent s'il n'existe pas
    chemin.parent.mkdir(parents=True, exist_ok=True)
    
    # Sauvegarder atomiquement
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, indent=2)


def obtenir_niveau_autonomie(domaine: str, user_id: str | None = None) -> int:
    """
    Obtient le niveau d'autonomie actuel pour un domaine donné.
    
    Si le domaine n'existe pas, retourne le niveau 0 (observation).
    
    Args:
        domaine: Le domaine d'action (ex: "fichiers_lecture").
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        Le niveau d'autonomie (0-3).
    """
    user_id = resoudre_utilisateur_actif(user_id)
    matrix = _charger_trust_matrix(user_id)
    
    if domaine in matrix["domaines"]:
        return matrix["domaines"][domaine]["niveau"]
    
    return NIVEAU_OBSERVATION


def doit_confirmer_action(capacite: str, user_id: str | None = None) -> bool:
    """
    Détermine si une action doit être confirmée avant exécution.
    
    Retourne True si le niveau est 0 ou 1 (observation ou proposition),
    False si le niveau est 2 ou 3 (action directe ou autonomie silencieuse).
    
    Args:
        capacite: Le nom de la capacité (ex: "fichiers.lire").
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        True si confirmation requise, False sinon.
    """
    domaine = extraire_domaine_capacite(capacite)
    niveau = obtenir_niveau_autonomie(domaine, user_id)
    
    return niveau <= NIVEAU_PROPOSITION


def enregistrer_resultat_action(
    capacite: str, succes: bool, user_id: str | None = None
) -> dict:
    """
    Enregistre le résultat d'une action et applique le mécanisme à cliquet.
    
    Met à jour les compteurs, applique la promotion ou rétrogradation,
    persiste sur disque et retourne le nouvel état du domaine.
    
    Args:
        capacite: Le nom de la capacité (ex: "fichiers.lire").
        succes: True si l'action a réussi, False si elle a échoué.
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        Le nouvel état du domaine après mise à jour.
    """
    user_id = resoudre_utilisateur_actif(user_id)
    domaine = extraire_domaine_capacite(capacite)
    
    matrix = _charger_trust_matrix(user_id)
    
    # Initialiser le domaine s'il n'existe pas
    if domaine not in matrix["domaines"]:
        matrix["domaines"][domaine] = _domaine_par_defaut()
    
    etat = matrix["domaines"][domaine]

    historique_recent = matrix.setdefault("historique_resultats", [])
    historique_recent.append({
        "date": datetime.now(timezone.utc).isoformat(),
        "domaine": domaine,
        "capacite": capacite,
        "succes": bool(succes),
    })
    matrix["historique_resultats"] = historique_recent[-1000:]
    
    # Mettre à jour les compteurs
    etat["actions_totales"] += 1
    
    if succes:
        etat["succes_consecutifs"] += 1
        # Recalculer le score (succès / total)
        etat["score"] = (etat["actions_totales"] - etat["echecs"]) / etat["actions_totales"]
        
        # Promotion : si seuil atteint et niveau < 3
        if etat["succes_consecutifs"] >= SEUIL_PROMOTION and etat["niveau"] < NIVEAU_AUTONOMIE_SILENCIEUSE:
            etat["niveau"] += 1
            etat["succes_consecutifs"] = 0  # Réinitialiser après promotion
    else:
        # Échec : rétrogradation immédiate
        etat["echecs"] += 1
        etat["succes_consecutifs"] = 0  # Réinitialiser les succès consécutifs
        
        # Rétrogradation : si niveau > 0
        if etat["niveau"] > NIVEAU_OBSERVATION:
            etat["niveau"] -= 1
        
        # Recalculer le score
        etat["score"] = (etat["actions_totales"] - etat["echecs"]) / etat["actions_totales"]
    
    # Sauvegarder la matrice
    _sauvegarder_trust_matrix(matrix, user_id)
    
    return etat.copy()


def obtenir_resume_confiance_compact(user_id: str | None = None) -> str:
    """
    Génère un résumé compact de la confiance pour affichage ou injection dans le prompt.
    
    Args:
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        Une chaîne de texte formatée décrivant l'état de confiance par domaine.
    """
    user_id = resoudre_utilisateur_actif(user_id)
    matrix = _charger_trust_matrix(user_id)
    
    lignes = [
        f"Matrice de Confiance (Utilisateur: {user_id}):",
    ]
    
    if not matrix["domaines"]:
        lignes.append("- Aucun domaine suivi")
        return "\n".join(lignes)
    
    # Trier les domaines par niveau décroissant
    domaines_tries = sorted(
        matrix["domaines"].items(),
        key=lambda x: x[1]["niveau"],
        reverse=True,
    )
    
    descriptions_niveaux = {
        0: "Observation",
        1: "Proposition",
        2: "Action + Notification",
        3: "Autonomie Silencieuse",
    }
    
    for domaine, etat in domaines_tries:
        niveau_desc = descriptions_niveaux.get(etat["niveau"], f"Niveau {etat['niveau']}")
        lignes.append(
            f"- {domaine}: Niveau {etat['niveau']} ({niveau_desc}) "
            f"| Score: {etat['score']:.2f} | "
            f"Succès consécutifs: {etat['succes_consecutifs']}/{SEUIL_PROMOTION} | "
            f"Total: {etat['actions_totales']} actions, {etat['echecs']} échecs"
        )
    
    return "\n".join(lignes)
