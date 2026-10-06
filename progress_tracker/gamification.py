"""Progress Tracker - Système de Gamification et Récompenses (CDC GreatOS Module 4.5).

Calcule les points d'effort (XP), les streaks d'habitudes et les niveaux de maîtrise
de l'utilisateur pour transformer la productivité en progression engageante.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

FICHIER_GAMIFICATION = Path(__file__).resolve().parent.parent / "learning" / "gamification_state.json"


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


def charger_etat_gamification() -> ProfilGamification:
    """Charge l'état courant de gamification."""
    if not FICHIER_GAMIFICATION.exists():
        return ProfilGamification()
    try:
        data = json.loads(FICHIER_GAMIFICATION.read_text(encoding="utf-8"))
        return ProfilGamification(
            niveau=data.get("niveau", 1),
            titre_rang=data.get("titre_rang", "Initié GreatOS"),
            points_xp=data.get("points_xp", 0),
            xp_palier_suivant=data.get("xp_palier_suivant", 500),
            objectifs_accomplis=data.get("objectifs_accomplis", 0),
            streak_actuel_jours=data.get("streak_actuel_jours", 0),
            meilleur_streak=data.get("meilleur_streak", 0),
        )
    except Exception:
        return ProfilGamification()


def sauvegarder_etat_gamification(profil: ProfilGamification) -> None:
    """Persiste l'état de gamification."""
    FICHIER_GAMIFICATION.parent.mkdir(parents=True, exist_ok=True)
    FICHIER_GAMIFICATION.write_text(json.dumps(profil.to_dict(), indent=2), encoding="utf-8")


def attribuer_xp(points: int, raison: str = "") -> Dict[str, Any]:
    """Ajoute des points XP et recalcule le niveau de l'utilisateur."""
    profil = charger_etat_gamification()
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

    sauvegarder_etat_gamification(profil)
    return {
        "points_ajoutes": points,
        "total_xp": profil.points_xp,
        "niveau": profil.niveau,
        "titre_rang": profil.titre_rang,
        "niveau_augmente": niveau_augmente,
        "raison": raison,
    }
