# progress_tracker/goals.py
"""Module Progress Tracker pour GreatOS - Modèles et suivi des objectifs.

Conforme au Cahier des Charges GreatOS (Section 4.5) :
Types d'objectifs : Quantitatifs, Qualitatifs, Habitudes.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class GoalType(str, Enum):
    QUANTITATIVE = "quantitatif"
    QUALITATIVE = "qualitatif"
    HABIT = "habitude"


class GoalStatus(str, Enum):
    ACTIVE = "actif"
    COMPLETED = "termine"
    PAUSED = "en_pause"
    ABANDONED = "abandonne"


@dataclass
class Milestone:
    id: str
    titre: str
    complete: bool = False
    date_completion: Optional[str] = None


@dataclass
class Goal:
    id: str
    titre: str
    description: str
    type_objectif: GoalType
    status: GoalStatus = GoalStatus.ACTIVE
    cible_valeur: float = 100.0
    valeur_actuelle: float = 0.0
    unite: str = "%"
    date_creation: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    date_echeance: Optional[str] = None
    jalons: List[Milestone] = field(default_factory=list)
    streak_actuel: int = 0
    streak_record: int = 0
    capacite_cible: Optional[str] = None

    @property
    def progression_pourcentage(self) -> float:
        if self.cible_valeur <= 0:
            return 100.0 if self.valeur_actuelle >= 0 else 0.0
        pct = (self.valeur_actuelle / self.cible_valeur) * 100.0
        return min(100.0, max(0.0, pct))


class GoalManager:
    """Gestionnaire persistant des objectifs GreatOS."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path(__file__).resolve().parent.parent / "goals.json"
        self._goals: Dict[str, Goal] = {}
        self._execution_metrics: Dict[str, Any] = {
            "total_actions": 0,
            "total_succes": 0,
            "total_echecs": 0,
            "duree_totale_ms": 0.0,
            "par_capacite": {},
            "par_module": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("goals", []):
                    jalons = [Milestone(**m) for m in item.get("jalons", [])]
                    item["jalons"] = jalons
                    item["type_objectif"] = GoalType(item.get("type_objectif", "qualitatif"))
                    item["status"] = GoalStatus(item.get("status", "actif"))
                    g = Goal(**item)
                    self._goals[g.id] = g
        except Exception:
            self._goals = {}

    def _save(self) -> None:
        try:
            serialized = []
            for g in self._goals.values():
                d = asdict(g)
                d["type_objectif"] = g.type_objectif.value
                d["status"] = g.status.value
                serialized.append(d)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"goals": serialized, "updated_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
        except Exception:
            pass

    def creer_objectif(
        self,
        id_obj: str,
        titre: str,
        description: str = "",
        type_obj: GoalType = GoalType.QUALITATIVE,
        cible: float = 100.0,
        unite: str = "%",
        date_echeance: Optional[str] = None,
        capacite_cible: Optional[str] = None,
    ) -> Goal:
        goal = Goal(
            id=id_obj,
            titre=titre,
            description=description,
            type_objectif=type_obj,
            cible_valeur=cible,
            unite=unite,
            date_echeance=date_echeance,
            capacite_cible=capacite_cible,
        )
        self._goals[id_obj] = goal
        self._save()
        return goal

    def mettre_a_jour_progression(self, id_obj: str, nouvelle_valeur: float) -> Optional[Goal]:
        if id_obj not in self._goals:
            return None
        goal = self._goals[id_obj]
        goal.valeur_actuelle = nouvelle_valeur
        if goal.progression_pourcentage >= 100.0:
            goal.status = GoalStatus.COMPLETED
        self._save()
        return goal

    def lister_objectifs(self, statut: Optional[GoalStatus] = None) -> List[Goal]:
        if statut:
            return [g for g in self._goals.values() if g.status == statut]
        return list(self._goals.values())

    def enregistrer_impact_capacite(
        self,
        resultat: Any,
        goal_id: Optional[str] = None,
        increment: float = 1.0,
    ) -> Dict[str, Any]:
        """Consomme un CapabilityResult structuré pour mesurer l'impact et mettre à jour les objectifs liés.

        Règle d'architecture : Ne jamais inventer ni incrémenter de progression si aucun objectif n'est lié.
        """
        cap = getattr(resultat, "capability", str(resultat))
        status = getattr(resultat, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status)
        is_success = status_val == "success"

        data = getattr(resultat, "data", {}) if isinstance(getattr(resultat, "data", {}), dict) else {}
        owner = str(data.get("owner") or "inconnu")
        duree_ms = float(data.get("duration_ms", 0.0) or 0.0)

        # 1. Enregistrement des métriques d'exécution globales
        self._execution_metrics["total_actions"] += 1
        if is_success:
            self._execution_metrics["total_succes"] += 1
        else:
            self._execution_metrics["total_echecs"] += 1
        self._execution_metrics["duree_totale_ms"] += duree_ms

        cap_metrics = self._execution_metrics["par_capacite"].setdefault(
            cap, {"succes": 0, "echecs": 0, "duree_ms": 0.0}
        )
        if is_success:
            cap_metrics["succes"] += 1
        else:
            cap_metrics["echecs"] += 1
        cap_metrics["duree_ms"] += duree_ms

        mod_metrics = self._execution_metrics["par_module"].setdefault(
            owner, {"succes": 0, "echecs": 0, "duree_ms": 0.0}
        )
        if is_success:
            mod_metrics["succes"] += 1
        else:
            mod_metrics["echecs"] += 1
        mod_metrics["duree_ms"] += duree_ms

        # 2. Raccordement strict aux objectifs actifs
        objectif_concerne: Optional[Goal] = None
        progression_appliquee = False

        if goal_id and goal_id in self._goals:
            target_goal = self._goals[goal_id]
            if target_goal.status == GoalStatus.ACTIVE:
                objectif_concerne = target_goal
        elif not goal_id:
            # Recherche d'un objectif actif ciblant explicitement cette capacité
            for g in self._goals.values():
                if g.status == GoalStatus.ACTIVE and g.capacite_cible == cap:
                    objectif_concerne = g
                    break

        if objectif_concerne and is_success:
            nouvelle_valeur = objectif_concerne.valeur_actuelle + increment
            self.mettre_a_jour_progression(objectif_concerne.id, nouvelle_valeur)
            progression_appliquee = True

        return {
            "capability": cap,
            "owner": owner,
            "status": status_val,
            "duree_ms": duree_ms,
            "objectif_lie": objectif_concerne.id if objectif_concerne else None,
            "progression_appliquee": progression_appliquee,
            "progression_pourcentage": objectif_concerne.progression_pourcentage if objectif_concerne else None,
        }

    def obtenir_metriques_execution(self) -> Dict[str, Any]:
        """Retourne les métriques d'exécution et de coût temporel agrégées."""
        return dict(self._execution_metrics)


goal_manager = GoalManager()


def enregistrer_impact_capacite(
    resultat: Any,
    goal_id: Optional[str] = None,
    increment: float = 1.0,
) -> Dict[str, Any]:
    """Point d'entrée module pour relier un CapabilityResult aux objectifs et métriques de Progress Tracker."""
    return goal_manager.enregistrer_impact_capacite(resultat, goal_id=goal_id, increment=increment)
