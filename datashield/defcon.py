# datashield/defcon.py
"""Gestionnaire d'état de sécurité DEFCON pour DataShield (GreatOS).

Définit les 5 niveaux de sécurité conformément au Cahier des Charges GreatOS :
- DEFCON 5 : Mode nominal / standard.
- DEFCON 4 : Vigilance accrue, journalisation renforcée.
- DEFCON 3 : Sécurité renforcée, confirmation obligatoire pour toute commande/script.
- DEFCON 2 : Alerte haute, isolement réseau, restrictions strictes.
- DEFCON 1 : Confinement critique, verrouillage complet du système.
"""

from enum import IntEnum
import threading
from typing import Callable, List


class DefconLevel(IntEnum):
    DEFCON_5 = 5  # Nominal
    DEFCON_4 = 4  # Vigilance
    DEFCON_3 = 3  # Sécurisé
    DEFCON_2 = 2  # Alerte haute
    DEFCON_1 = 1  # Confinement critique


class DefconManager:
    """Gestionnaire singleton de l'état DEFCON de GreatOS."""

    def __init__(self, default_level: DefconLevel = DefconLevel.DEFCON_5):
        self._level = default_level
        self._lock = threading.Lock()
        self._listeners: List[Callable[[DefconLevel, DefconLevel], None]] = []

    @property
    def current_level(self) -> DefconLevel:
        with self._lock:
            return self._level

    def set_level(self, new_level: DefconLevel) -> None:
        """Modifie le niveau DEFCON et notifie les observateurs."""
        old_level = None
        with self._lock:
            if self._level != new_level:
                old_level = self._level
                self._level = new_level

        if old_level is not None:
            for listener in self._listeners:
                try:
                    listener(old_level, new_level)
                except Exception:
                    pass

    def add_listener(self, callback: Callable[[DefconLevel, DefconLevel], None]) -> None:
        """Enregistre un observateur lors des transitions d'état."""
        self._listeners.append(callback)

    def is_action_allowed(self, is_destructive: bool, is_system_call: bool) -> bool:
        """Vérifie si une action est autorisée sous le niveau DEFCON actuel."""
        lvl = self.current_level
        if lvl == DefconLevel.DEFCON_1:
            return False
        if lvl == DefconLevel.DEFCON_2 and is_destructive:
            return False
        if lvl <= DefconLevel.DEFCON_3 and is_system_call:
            return False
        return True


# Singleton d'application
defcon = DefconManager()
