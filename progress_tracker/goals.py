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
from typing import Dict, List, Optional


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

    def creer_objectif(self, id_obj: str, titre: str, description: str = "", type_obj: GoalType = GoalType.QUALITATIVE, cible: float = 100.0, unite: str = "%", date_echeance: Optional[str] = None) -> Goal:
        goal = Goal(id=id_obj, titre=titre, description=description, type_objectif=type_obj, cible_valeur=cible, unite=unite, date_echeance=date_echeance)
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


goal_manager = GoalManager()
