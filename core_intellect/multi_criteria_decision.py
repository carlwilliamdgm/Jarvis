"""Core Intellect - Moteur Décisionnel Multi-Critères (CDC GreatOS Module 4.2).

Rôle : Le moteur invisible qui analyse et décide.
- Analyse situationnelle holistique
- Évaluation multi-critères : Urgence [1-5], Importance [1-5], Effort estimé [1-5]
- Score d'arbitrage = (Importance * 0.5) + (Urgence * 0.35) - (Effort * 0.15)
- Résolution automatique de conflits de tâches ou de ressources
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class PrioriteNiveau(str, Enum):
    CRITIQUE = "critique"       # Score >= 3.8
    HAUTE = "haute"             # Score >= 2.8
    MOYENNE = "moyenne"         # Score >= 1.8
    BASSE = "basse"             # Score < 1.8


@dataclass(frozen=True)
class EvaluationMultiCriteres:
    nom: str
    urgence: int        # 1 (faible) à 5 (immédiat)
    importance: int     # 1 (accessoire) à 5 (vital pour l'utilisateur)
    effort: int         # 1 (trivial/rapide) à 5 (lourd/complexe)
    score_decision: float
    priorite: PrioriteNiveau
    justification: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priorite"] = self.priorite.value
        return d


def evaluer_decision(
    nom: str,
    urgence: int = 3,
    importance: int = 3,
    effort: int = 2,
    contexte_description: str = "",
) -> EvaluationMultiCriteres:
    """Calcule le score de décision multi-critères selon l'équation CDC Core Intellect."""
    # Borner les entrées entre 1 et 5
    u = max(1, min(5, int(urgence)))
    i = max(1, min(5, int(importance)))
    e = max(1, min(5, int(effort)))

    # Pondération rationnelle : L'importance domine (50%), l'urgence pousse (35%), l'effort modère (15%)
    score = round((i * 0.50) + (u * 0.35) - (e * 0.15), 2)

    if score >= 3.5:
        niveau = PrioriteNiveau.CRITIQUE
    elif score >= 2.6:
        niveau = PrioriteNiveau.HAUTE
    elif score >= 1.7:
        niveau = PrioriteNiveau.MOYENNE
    else:
        niveau = PrioriteNiveau.BASSE

    justif = f"Importance: {i}/5, Urgence: {u}/5, Effort: {e}/5 -> Score {score:.2f} ({niveau.value})"
    if contexte_description:
        justif += f" | {contexte_description}"

    return EvaluationMultiCriteres(
        nom=nom,
        urgence=u,
        importance=i,
        effort=e,
        score_decision=score,
        priorite=niveau,
        justification=justif,
    )


def arbitrer_priorite_taches(taches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classe et arbitre une liste de tâches candidates par ordre de priorité décroissante."""
    evaluations = []
    for t in taches:
        nom = t.get("nom") or t.get("description") or "Tâche sans nom"
        u = t.get("urgence", 3)
        i = t.get("importance", 3)
        e = t.get("effort", 2)
        desc = t.get("contexte", "")
        ev = evaluer_decision(nom, u, i, e, desc)
        d = t.copy()
        d["evaluation"] = ev.to_dict()
        d["score_decision"] = ev.score_decision
        evaluations.append(d)

    # Tri déterministe décroissant par score de décision
    evaluations.sort(key=lambda x: x["score_decision"], reverse=True)
    return evaluations


def resoudre_conflit_ressources(
    conflits: List[Dict[str, Any]],
    ressource_disponible: str,
) -> Dict[str, Any]:
    """Arbitre automatiquement lorsqu'un conflit d'accès à une ressource survient."""
    if not conflits:
        return {"choix_retenu": None, "raison": "Aucun conflit soumis"}

    taches_arbitrees = arbitrer_priorite_taches(conflits)
    gagnante = taches_arbitrees[0]
    autres = [t.get("nom") for t in taches_arbitrees[1:]]

    return {
        "ressource": ressource_disponible,
        "choix_retenu": gagnante.get("nom"),
        "score_vainqueur": gagnante.get("score_decision"),
        "taches_reportees": autres,
        "raison": (
            f"La tâche '{gagnante.get('nom')}' a été retenue en priorité (score {gagnante.get('score_decision')}) "
            f"face aux alternatives reportées : {', '.join(autres) if autres else 'aucune'}."
        ),
    }
