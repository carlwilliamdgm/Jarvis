"""Daemon de Veille Proactive - Surveillance système en arrière-plan."""

import threading
import time
from typing import Any, Dict, Set, Optional

from context_engine.system_monitor import obtenir_etat_systeme_complet, detecter_anomalies


class DaemonProactif(threading.Thread):
    """
    Thread démon surveillant proactivement l'état système.
    
    Fonctionne en arrière-plan pour détecter les anomalies et émettre
    des alertes via l'EventBus sans attendre d'interaction utilisateur.
    """
    
    def __init__(
        self,
        event_bus: Any,
        intervalle_secondes: float = 60.0
    ):
        """
        Initialise le daemon proactif.
        
        Args:
            event_bus: Instance de EventBus pour émettre les alertes
            intervalle_secondes: Fréquence des cycles de surveillance (défaut: 60s)
        """
        super().__init__(daemon=True)
        self._event_bus = event_bus
        self._intervalle_secondes = intervalle_secondes
        self._stop_event = threading.Event()
        self._alertes_actives: Set[str] = set()
    
    def run(self) -> None:
        """Boucle principale du daemon."""
        while not self._stop_event.is_set():
            try:
                self._cycle_veille()
            except Exception as e:
                # Le daemon ne doit jamais crasher l'application
                print(f"[DaemonProactif] Erreur dans le cycle: {e}")
            
            # Attendre l'intervalle ou jusqu'à l'arrêt
            self._stop_event.wait(self._intervalle_secondes)
    
    def _cycle_veille(self) -> None:
        """
        Exécute un cycle de surveillance système.
        
        Récupère l'état système, détecte les anomalies et émet des alertes
        si nécessaire (avec mécanisme anti-spam).
        """
        etat = obtenir_etat_systeme_complet()
        anomalies = detecter_anomalies(etat)
        
        # Générer des identifiants uniques pour les anomalies actuelles
        anomalies_actuelles = set()
        for anomalie in anomalies:
            identifiant = self._generer_identifiant_anomalie(anomalie)
            anomalies_actuelles.add(identifiant)
            
            # Émettre l'alerte si elle n'est pas déjà active
            if identifiant not in self._alertes_actives:
                self._alertes_actives.add(identifiant)
                self._emitter_alerte(anomalie)
        
        # Retirer les alertes qui ne sont plus présentes (réarmement)
        alertes_levees = self._alertes_actives - anomalies_actuelles
        for identifiant in alertes_levees:
            self._alertes_actives.discard(identifiant)
            type_anomalie, _, mountpoint = identifiant.partition(":")
            self._emitter_alerte_resolue({"type": type_anomalie, "mountpoint": mountpoint})
    
    def _generer_identifiant_anomalie(self, anomalie: Dict[str, Any]) -> str:
        """
        Génère un identifiant unique pour une anomalie.
        
        Args:
            anomalie: Dictionnaire décrivant l'anomalie
            
        Returns:
            Identifiant unique sous forme de chaîne
        """
        type_anomalie = anomalie.get("type", "inconnu")
        mountpoint = anomalie.get("mountpoint", "")
        
        if mountpoint:
            return f"{type_anomalie}:{mountpoint}"
        return type_anomalie
    
    def _emitter_alerte(self, anomalie: Dict[str, Any]) -> None:
        """
        Émet une alerte proactive via l'EventBus.
        
        Args:
            anomalie: Dictionnaire décrivant l'anomalie
        """
        if self._event_bus:
            emitter = getattr(self._event_bus, "emit_broadcast", self._event_bus.emit)
            emitter("alerte_proactive", anomalie)

    def _emitter_alerte_resolue(self, anomalie: Dict[str, Any]) -> None:
        if self._event_bus:
            emitter = getattr(self._event_bus, "emit_broadcast", self._event_bus.emit)
            emitter("alerte_proactive_resolue", anomalie)
    
    def arreter(self) -> None:
        """Arrête proprement le daemon."""
        self._stop_event.set()
