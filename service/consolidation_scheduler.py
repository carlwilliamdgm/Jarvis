"""Thread de consolidation nocturne, lancé avec le serveur GreatOS."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("jarvis.consolidation")


class ConsolidationScheduler(threading.Thread):
    def __init__(self, intervalle_secondes: float = 60.0) -> None:
        super().__init__(name="greatos-consolidation", daemon=True)
        self._intervalle = intervalle_secondes
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                from learning.consolidation_engine import consolider_si_due
                consolider_si_due()
            except Exception:
                logger.exception("Échec de consolidation nocturne")
            self._stop_event.wait(self._intervalle)

    def arreter(self) -> None:
        self._stop_event.set()
