#context_engine/user_profile.py

"""
Moteur de Profil Multi-Utilisateurs & Session Agnostique (Jalon 2).

Ce module gère l'isolation des profils utilisateurs sur disque et fournit
une API pour résoudre, charger et sauvegarder les profils utilisateur.
"""

import getpass
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from context_engine.paths import JARVIS_DIR
from datashield.crypto import crypto_engine


# Chemin du dossier des profils
PROFILES_DIR = JARVIS_DIR / "learning" / "profiles"
_ENCRYPTED_PROFILE_KEY = "__greatos_encrypted_profile_v1__"


def _slug_user_id(user_id: str) -> str:
    """
    Nettoie et normalise un user_id pour un stockage sain sur disque.
    
    Conserve uniquement les caractères alphanumériques, underscores et tirets.
    Nettoie les underscores et tirets en trop au début et à la fin.
    """
    if not user_id:
        return "default"
    # Remplacer les espaces et caractères spéciaux par des underscores
    slug = re.sub(r"[^\w\-]", "_", user_id)
    # Nettoyer les underscores et tirets en trop au début et à la fin
    slug = slug.strip("_-")
    # Éviter les slug vides après nettoyage
    return slug if slug else "default"


def resoudre_utilisateur_actif(user_id_explicite: str | None = None) -> str:
    """
    Résout dynamiquement l'identifiant de l'utilisateur actif.
    
    Priorité :
    1. user_id_explicite fourni (ex: depuis Interface Morphique ou API)
    2. Variable d'environnement GREATOS_USER
    3. Utilisateur de l'OS via getpass.getuser() / os.getlogin()
    
    Args:
        user_id_explicite: Identifiant utilisateur explicite optionnel.
        
    Returns:
        L'identifiant utilisateur normalisé (slug alphanumérique sain).
    """
    if user_id_explicite:
        return _slug_user_id(user_id_explicite)
    
    # Fallback variable d'environnement
    env_user = os.environ.get("GREATOS_USER")
    if env_user:
        return _slug_user_id(env_user)
    
    # Fallback utilisateur OS
    try:
        os_user = getpass.getuser()
        if os_user:
            return _slug_user_id(os_user)
    except Exception:
        pass
    
    try:
        os_user = os.getlogin()
        if os_user:
            return _slug_user_id(os_user)
    except Exception:
        pass
    
    # Fallback ultime
    return "default"


def _profil_par_defaut(user_id: str) -> dict:
    """
    Génère un profil par défaut sain pour un nouvel utilisateur.
    
    Args:
        user_id: L'identifiant utilisateur normalisé.
        
    Returns:
        Un dictionnaire de profil initialisé avec des valeurs par défaut.
    """
    return {
        "user_id": user_id,
        "nom": user_id.capitalize(),
        "role": "utilisateur",  # "admin", "developpeur", "visiteur"
        "langue": "français",
        "style_cognitif": {
            "format_prefere": "synthese",  # "synthese", "detaille", "technique"
            "concis": True,
            "niveau_technique": 0.5,
        },
        "rythme_activite": {
            "derniere_session": "",
            "nombre_interactions": 0,
            "creneaux_heures": [],
        },
        "directives_personnelles": {},
    }


def _chemin_profil(user_id: str) -> Path:
    """
    Retourne le chemin du fichier profile.json pour un utilisateur donné.
    
    Args:
        user_id: L'identifiant utilisateur normalisé.
        
    Returns:
        Le chemin complet vers le fichier de profil.
    """
    return PROFILES_DIR / user_id / "profile.json"


def charger_profil(user_id: str | None = None) -> dict:
    """
    Charge le profil d'un utilisateur depuis le disque.
    
    Si le profil n'existe pas, il est créé automatiquement avec le profil par défaut.
    
    Args:
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        Le dictionnaire du profil utilisateur.
    """
    user_id = resoudre_utilisateur_actif(user_id)
    chemin = _chemin_profil(user_id)
    
    # Créer le dossier parent s'il n'existe pas
    chemin.parent.mkdir(parents=True, exist_ok=True)
    
    # Charger le profil s'il existe
    if chemin.exists():
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                profil = json.load(f)
            if not isinstance(profil, dict):
                raise RuntimeError("Contenu du profil invalide; lecture refusée.")
            if _ENCRYPTED_PROFILE_KEY in profil:
                if set(profil) != {_ENCRYPTED_PROFILE_KEY} or not isinstance(profil[_ENCRYPTED_PROFILE_KEY], str):
                    raise RuntimeError("Enveloppe de profil chiffrée invalide; lecture refusée.")
                raw_profile = crypto_engine.decrypt(profil[_ENCRYPTED_PROFILE_KEY], strict=True)
                profil = json.loads(raw_profile)
            else:
                if not crypto_engine.is_enabled:
                    raise RuntimeError("Migration du profil refusée : chiffrement DataShield indisponible.")
                # Migre le format JSON historique vers une enveloppe intégralement chiffrée.
                sauvegarder_profil(profil, user_id)
            if not isinstance(profil, dict):
                raise RuntimeError("Contenu du profil invalide; lecture refusée.")
            profil["user_id"] = user_id
            return profil
        except (json.JSONDecodeError, IOError) as exc:
            raise RuntimeError("Profil illisible; lecture refusée plutôt que recréée.") from exc
    
    # Créer un nouveau profil par défaut
    profil = _profil_par_defaut(user_id)
    sauvegarder_profil(profil, user_id)
    return profil


def sauvegarder_profil(profil: dict, user_id: str | None = None) -> None:
    """
    Sauvegarde le profil d'un utilisateur sur le disque.
    
    Args:
        profil: Le dictionnaire du profil à sauvegarder.
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
    """
    user_id = resoudre_utilisateur_actif(user_id)
    chemin = _chemin_profil(user_id)
    
    # Créer le dossier parent s'il n'existe pas
    chemin.parent.mkdir(parents=True, exist_ok=True)
    
    # S'assurer que le user_id est correct
    profil["user_id"] = user_id
    
    # Mettre à jour la dernière session
    if "rythme_activite" in profil:
        profil["rythme_activite"]["derniere_session"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not crypto_engine.is_enabled:
        raise RuntimeError("Écriture du profil refusée : chiffrement DataShield indisponible.")
    serialized = json.dumps(profil, ensure_ascii=False, separators=(",", ":"))
    envelope = {_ENCRYPTED_PROFILE_KEY: crypto_engine.encrypt(serialized)}
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=chemin.parent, prefix=f"{chemin.name}.",
            suffix=".tmp", delete=False,
        ) as f:
            temp_path = Path(f.name)
            json.dump(envelope, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, chemin)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def mettre_a_jour_directive_profil(cle: str, valeur: str, user_id: str | None = None) -> None:
    """
    Enregistre une directive personnelle dans le profil d'un utilisateur.
    
    Args:
        cle: La clé de la directive.
        valeur: La valeur/contenu de la directive.
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
    """
    profil = charger_profil(user_id)
    
    if "directives_personnelles" not in profil:
        profil["directives_personnelles"] = {}
    
    profil["directives_personnelles"][cle] = valeur
    
    # Incrémenter le compteur d'interactions
    if "rythme_activite" in profil:
        profil["rythme_activite"]["nombre_interactions"] = profil["rythme_activite"].get("nombre_interactions", 0) + 1
    
    sauvegarder_profil(profil, user_id)


def obtenir_contexte_profil_compact(user_id: str | None = None) -> str:
    """
    Génère un bloc textuel compact prêt à être injecté dans le prompt de Core Intellect.
    
    Args:
        user_id: Identifiant utilisateur optionnel. Si None, résolu dynamiquement.
        
    Returns:
        Une chaîne de texte formatée décrivant le profil utilisateur actif.
    """
    profil = charger_profil(user_id)
    
    nom = profil.get("nom", profil.get("user_id", "Inconnu"))
    role = profil.get("role", "utilisateur")
    
    style = profil.get("style_cognitif", {})
    format_prefere = style.get("format_prefere", "synthese")
    concis = style.get("concis", True)
    
    directives = profil.get("directives_personnelles", {})
    
    lignes = [
        "Profil Utilisateur Actif :",
        f"- Identité : {nom} (rôle : {role})",
        f"- Préférence de réponse : {format_prefere}, concision : {concis}",
    ]
    
    if directives:
        lignes.append("- Directives personnelles en vigueur :")
        for cle, valeur in directives.items():
            lignes.append(f"  • {valeur}")
    else:
        lignes.append("- Directives personnelles en vigueur : aucune")
    
    return "\n".join(lignes)
