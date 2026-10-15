"""Progress Tracker - Système de Gamification et Récompenses (CDC GreatOS Module 4.5).

Calcule les points d'effort (XP), les streaks d'habitudes et les niveaux de maîtrise
de l'utilisateur pour transformer la productivité en progression engageante.
"""

from __future__ import annotations

import json
import threading
from uuid import uuid4
from dataclasses import asdict, dataclass
from typing import Any, Dict

from context_engine.paths import JARVIS_DIR
from context_engine.user_profile import charger_profil, resoudre_utilisateur_actif, transaction_profil


_GAMIFICATION_LOCK = threading.RLock()
_GAMIFICATION_PROFILE_KEY = "gamification"
_LEGACY_GAMIFICATION_PATH = JARVIS_DIR / "learning" / "gamification_state.json"


@dataclass
class ProfilGamification:
    niveau: int = 1
    titre_rang: str = "Initié GreatOS"
    points_xp: int = 0
    xp_palier_suivant: int = 500
    objectifs_accomplis: int = 0
    streak_actuel_jours: int = 0
    meilleur_streak: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


TITRES_NIVEAUX = {
    1: "Initié GreatOS",
    2: "Praticien de l'Automatisation",
    3: "Architecte Logiciel",
    4: "Maître Souverain de GreatOS",
}


def _profil_depuis_donnees(data: Any) -> ProfilGamification:
    if data is None:
        return ProfilGamification()
    if not isinstance(data, dict):
        raise RuntimeError("État de gamification invalide; lecture refusée.")
    try:
        values = {
            "niveau": data.get("niveau", 1),
            "titre_rang": data.get("titre_rang", "Initié GreatOS"),
            "points_xp": data.get("points_xp", 0),
            "xp_palier_suivant": data.get("xp_palier_suivant", 500),
            "objectifs_accomplis": data.get("objectifs_accomplis", 0),
            "streak_actuel_jours": data.get("streak_actuel_jours", 0),
            "meilleur_streak": data.get("meilleur_streak", 0),
        }
        for name, value in values.items():
            if name == "titre_rang":
                if not isinstance(value, str):
                    raise ValueError(name)
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(name)
        if values["niveau"] < 1:
            raise ValueError("niveau")
        return ProfilGamification(**values)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("État de gamification invalide; lecture refusée.") from exc


def _charger_avec_migration_legacy(user_id: str) -> ProfilGamification:
    profile = charger_profil(user_id)
    current = profile.get(_GAMIFICATION_PROFILE_KEY)

    # L'ancien fichier global est attribué une seule fois, au profil actif choisi.
    if user_id != resoudre_utilisateur_actif() or not _LEGACY_GAMIFICATION_PATH.exists():
        return _profil_depuis_donnees(current)

    try:
        original_bytes = _LEGACY_GAMIFICATION_PATH.read_bytes()
        legacy_data = json.loads(original_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Migration de l'ancienne progression impossible; fichier conservé.") from exc
    legacy_profile = _profil_depuis_donnees(legacy_data)

    if current is None:
        with transaction_profil(user_id) as writable_profile:
            if writable_profile.get(_GAMIFICATION_PROFILE_KEY) is None:
                writable_profile[_GAMIFICATION_PROFILE_KEY] = legacy_profile.to_dict()
            else:
                legacy_profile = _profil_depuis_donnees(writable_profile[_GAMIFICATION_PROFILE_KEY])
    else:
        current_profile = _profil_depuis_donnees(current)
        if current_profile.to_dict() != legacy_profile.to_dict():
            raise RuntimeError(
                "Migration de progression interrompue : le profil actif et l'ancien état diffèrent."
            )
        legacy_profile = current_profile

    verified = _profil_depuis_donnees(charger_profil(user_id).get(_GAMIFICATION_PROFILE_KEY))
    if verified.to_dict() != legacy_profile.to_dict():
        raise RuntimeError("Vérification de la migration de progression échouée; fichier source conservé.")
    staged_legacy = _LEGACY_GAMIFICATION_PATH.with_name(
        f"{_LEGACY_GAMIFICATION_PATH.name}.migration-{uuid4().hex}"
    )
    try:
        _LEGACY_GAMIFICATION_PATH.rename(staged_legacy)
    except FileNotFoundError:
        # Une autre instance a pu terminer la migration après notre lecture.
        if _profil_depuis_donnees(charger_profil(user_id).get(_GAMIFICATION_PROFILE_KEY)).to_dict() == legacy_profile.to_dict():
            return legacy_profile
        raise RuntimeError("L'ancien état a disparu pendant la migration; aucune donnée n'a été supprimée.")
    except OSError as exc:
        raise RuntimeError(
            "Progression copiée et vérifiée dans le profil chiffré, mais le fichier legacy ne peut pas être isolé."
        ) from exc

    try:
        if staged_legacy.read_bytes() != original_bytes:
            # Rename captured a concurrent version. On Windows, rename fails
            # rather than replacing an existing destination, preserving both.
            try:
                staged_legacy.rename(_LEGACY_GAMIFICATION_PATH)
            except OSError:
                raise RuntimeError(
                    f"L'ancien état a changé durant la migration; copie conservée sous {staged_legacy.name}."
                )
            raise RuntimeError("L'ancien état a changé durant la migration; fichier source restauré.")
        staged_legacy.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"Copie chiffrée vérifiée, mais le fichier legacy conservé sous {staged_legacy.name} n'a pas pu être retiré."
        ) from exc
    return verified


def charger_etat_gamification(user_id: str | None = None) -> ProfilGamification:
    """Charge l'état de l'utilisateur depuis son profil DataShield chiffré."""
    with _GAMIFICATION_LOCK:
        resolved_user_id = resoudre_utilisateur_actif(user_id)
        return _charger_avec_migration_legacy(resolved_user_id)


def sauvegarder_etat_gamification(profil: ProfilGamification, user_id: str | None = None) -> None:
    """Persiste l'état dans le profil local chiffré de l'utilisateur."""
    if not isinstance(profil, ProfilGamification):
        raise TypeError("profil doit être une instance de ProfilGamification.")
    with _GAMIFICATION_LOCK:
        _charger_avec_migration_legacy(resoudre_utilisateur_actif(user_id))
        with transaction_profil(user_id) as profile:
            profile[_GAMIFICATION_PROFILE_KEY] = profil.to_dict()


def attribuer_xp(points: int, raison: str = "", user_id: str | None = None) -> Dict[str, Any]:
    """Ajoute des points XP et recalcule le niveau de l'utilisateur."""
    if isinstance(points, bool) or not isinstance(points, int):
        raise TypeError("points doit être un entier.")
    user_id = resoudre_utilisateur_actif(user_id)
    with _GAMIFICATION_LOCK:
        _charger_avec_migration_legacy(user_id)
        with transaction_profil(user_id) as profile:
            profil = _profil_depuis_donnees(profile.get(_GAMIFICATION_PROFILE_KEY))
            profil.points_xp += max(0, points)

            # Calcul du niveau : palier exponentiel doux
            # Niv 1: 0-500, Niv 2: 501-1500, Niv 3: 1501-3500, Niv 4: 3501+
            ancien_niveau = profil.niveau
            if profil.points_xp >= 3500:
                profil.niveau = 4
                profil.xp_palier_suivant = 7000
            elif profil.points_xp >= 1500:
                profil.niveau = 3
                profil.xp_palier_suivant = 3500
            elif profil.points_xp >= 500:
                profil.niveau = 2
                profil.xp_palier_suivant = 1500
            else:
                profil.niveau = 1
                profil.xp_palier_suivant = 500

            profil.titre_rang = TITRES_NIVEAUX.get(profil.niveau, "Maître de GreatOS")
            niveau_augmente = profil.niveau > ancien_niveau
            profile[_GAMIFICATION_PROFILE_KEY] = profil.to_dict()
    return {
        "points_ajoutes": max(0, points),
        "total_xp": profil.points_xp,
        "niveau": profil.niveau,
        "titre_rang": profil.titre_rang,
        "niveau_augmente": niveau_augmente,
        "raison": raison,
    }
