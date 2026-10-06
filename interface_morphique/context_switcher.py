"""Context Switcher - Moteur de morphing d'interface contextuelle (GreatOS Module 8).

Détermine dynamiquement le layout d'interface optimal parmi les 8 layouts
spécifiés dans le Cahier des Charges GreatOS, en réagissant aux événements système
et applicatifs diffusés via l'EventBus :

1. CHAT          : Dialogue conversationnel par défaut
2. FOCUS         : Plein écran ou travail intensif détecté (IDE, code, rédaction)
3. DASHBOARD     : Supervision système et métriques globales
4. VOCAL_HUD     : Interaction vocale en cours (wake word, écoute, synthèse)
5. TASK_RUNNER   : Exécution de workflow ou plan d'action autonome actif
6. WEB_NAV       : Session de navigation web persistante active
7. IDLE          : Inactivité prolongée ou état de repos
8. DEFCON_ALERT  : Alerte de sécurité ou incident critique
"""

from __future__ import annotations

from enum import Enum
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from core_intellect.event_bus import get_event_bus

logger = logging.getLogger(__name__)


class MorphicLayout(str, Enum):
    """Les 8 layouts contextuels d'Interface Morphique selon le CDC GreatOS."""

    CHAT = "chat"
    FOCUS = "focus"
    DASHBOARD = "dashboard"
    VOCAL_HUD = "vocal_hud"
    TASK_RUNNER = "task_runner"
    WEB_NAV = "web_nav"
    IDLE = "idle"
    DEFCON_ALERT = "defcon_alert"


class MorphicContextEngine:
    """Moteur de décision et de transition des layouts de l'Interface Morphique."""

    # Applications considérées comme mode FOCUS
    FOCUS_APPS = {
        "code", "cursor", "pycharm", "intellij", "devenv",
        "sublime_text", "notepad++", "obsidian", "terminal",
        "powershell", "cmd", "alacritty", "wt",
    }

    def __init__(self):
        self._current_layout: MorphicLayout = MorphicLayout.CHAT
        self._layout_lock = threading.Lock()
        self._listeners: list[Callable[[MorphicLayout, Dict[str, Any]], None]] = []

        # État interne des différents sous-systèmes
        self._os_context: Dict[str, Any] = {}
        self._vocal_actif: bool = False
        self._task_active: bool = False
        self._web_nav_active: bool = False
        self._defcon_alert_active: bool = False
        self._derniere_activite = time.time()
        self._idle_threshold_seconds = 300  # 5 minutes

        self._listener_queue = None
        self._listener_thread = None
        self._stop_event = threading.Event()

    def get_current_layout(self) -> MorphicLayout:
        """Retourne le layout contextuel actif."""
        with self._layout_lock:
            return self._current_layout

    def abonner_changement_layout(
        self, callback: Callable[[MorphicLayout, Dict[str, Any]], None]
    ) -> None:
        """Abonne un listener à chaque changement de layout."""
        with self._layout_lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def _evaluer_layout(self) -> MorphicLayout:
        """Évalue l'état complet du système et décide du layout contextuel prioritaire."""
        # 1. Priorité absolue : Alerte de sécurité DEFCON
        if self._defcon_alert_active:
            return MorphicLayout.DEFCON_ALERT

        # 2. Priorité 2 : Interaction vocale active
        if self._vocal_actif:
            return MorphicLayout.VOCAL_HUD

        # 3. Priorité 3 : Workflow / Tâche autonome active
        if self._task_active:
            return MorphicLayout.TASK_RUNNER

        # 4. Priorité 4 : Session de navigation web active
        if self._web_nav_active:
            return MorphicLayout.WEB_NAV

        # 5. Priorité 5 : Plein écran, appli de code ou Deep Work cognitif (Focus)
        processus = (self._os_context.get("processus") or "").lower().replace(".exe", "")
        est_plein_ecran = bool(self._os_context.get("plein_ecran", False))
        est_deep_work = False
        try:
            from context_engine.four_dimensions import capturer_contexte_quadridimensionnel, ChargeCognitive
            dim_ctx = capturer_contexte_quadridimensionnel()
            est_deep_work = dim_ctx.cognitif.charge == ChargeCognitive.DEEP_WORK
        except Exception:
            pass

        if est_plein_ecran or est_deep_work or processus in self.FOCUS_APPS:
            return MorphicLayout.FOCUS

        # 6. Priorité 6 : Inactivité prolongée (Idle)
        if time.time() - self._derniere_activite > self._idle_threshold_seconds:
            return MorphicLayout.IDLE

        # 7. Layout par défaut : Conversation / Chat
        return MorphicLayout.CHAT

    def _transitionner_si_necessaire(self, declencheur: str) -> None:
        """Bascule vers le nouveau layout si une transition est requise."""
        nouvel_layout = self._evaluer_layout()
        avec_changement = False
        anciens_listeners = []

        with self._layout_lock:
            if nouvel_layout != self._current_layout:
                ancien_layout = self._current_layout
                self._current_layout = nouvel_layout
                avec_changement = True
                anciens_listeners = list(self._listeners)
                logger.info(
                    "Transition morphique: %s -> %s (déclencheur: %s)",
                    ancien_layout.value,
                    nouvel_layout.value,
                    declencheur,
                )

        if avec_changement:
            payload = {
                "ancien_layout": ancien_layout.value,
                "nouveau_layout": nouvel_layout.value,
                "declencheur": declencheur,
                "timestamp": time.time(),
                "os_context": dict(self._os_context),
            }
            # Émettre également sur l'EventBus global
            try:
                get_event_bus().emit_broadcast("morphic_layout_changed", payload)
            except Exception as e:
                logger.debug("Échec broadcast morphic_layout_changed: %s", e)

            for cb in anciens_listeners:
                try:
                    cb(nouvel_layout, payload)
                except Exception as e:
                    logger.debug("Erreur callback morphic layout: %s", e)

    def notifier_evenement(self, event_type: str, data: Dict[str, Any]) -> None:
        """Reçoit un événement et met à jour l'état contextuel."""
        self._derniere_activite = time.time()

        if event_type == "os_context_changed":
            self._os_context = data
            self._transitionner_si_necessaire("os_context_changed")

        elif event_type in ("vocal_state_changed", "voice_overlay"):
            state = str(data.get("state", "idle")).lower()
            self._vocal_actif = state not in ("idle", "error", "closed")
            self._transitionner_si_necessaire(f"voice_state:{state}")

        elif event_type in ("stark_activated", "tool_started"):
            self._task_active = True
            self._transitionner_si_necessaire("task_started")

        elif event_type in ("stark_desactive", "tool_completed", "tool_failed"):
            self._task_active = False
            self._transitionner_si_necessaire("task_ended")

        elif event_type == "browser_session":
            state = str(data.get("state", "")).lower()
            self._web_nav_active = state not in ("closed", "idle", "")
            self._transitionner_si_necessaire(f"browser_session:{state}")

        elif event_type == "alerte_proactive":
            type_alerte = str(data.get("type", "")).lower()
            if "defcon" in type_alerte or "securite" in type_alerte:
                self._defcon_alert_active = True
                self._transitionner_si_necessaire("defcon_alert")

        elif event_type == "alerte_proactive_resolue":
            self._defcon_alert_active = False
            self._transitionner_si_necessaire("defcon_resolved")

    def _ecouter_event_bus(self) -> None:
        """Consomme les événements diffusés sur l'EventBus global de GreatOS."""
        bus = get_event_bus()
        self._listener_queue = bus.subscribe_broadcast()

        while not self._stop_event.is_set():
            try:
                event = self._listener_queue.get(timeout=0.2)
                if event and isinstance(event, dict):
                    event_type = event.get("type", "")
                    event_data = event.get("data", {})
                    self.notifier_evenement(event_type, event_data)
            except Exception:
                continue

        bus.unsubscribe(self._listener_queue)

    def demarrer(self) -> None:
        """Démarre le switch automatique en arrière-plan."""
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._ecouter_event_bus,
            name="GreatOS_MorphicContextEngine",
            daemon=True,
        )
        self._listener_thread.start()

    def arreter(self) -> None:
        """Arrête le moteur de morphing."""
        self._stop_event.set()
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=1.0)


# Instance globale partagée
_morphic_engine: Optional[MorphicContextEngine] = None
_morphic_lock = threading.Lock()


def get_morphic_engine() -> MorphicContextEngine:
    """Retourne l'instance singleton du moteur de morphing contextuel."""
    global _morphic_engine
    if _morphic_engine is None:
        with _morphic_lock:
            if _morphic_engine is None:
                _morphic_engine = MorphicContextEngine()
    return _morphic_engine
