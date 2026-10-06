# core_intellect/event_bus.py
"""Bus d'événements partagé entre les modules GreatOS.

Extrait de jarvis/agent.py pour casser le couplage taskflow → jarvis.
Utilisé par :
- jarvis/agent.py  (instance globale event_bus)
- interface_morphique/server.py (SSE subscribers)
- taskflow/browser_session.py (émission d'événements browser)
"""

import queue
import threading
from typing import Optional


class EventBus:
    """Bus d'événements thread-safe pour la communication inter-module."""

    def __init__(self):
        self._queues = set()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._proactive_alerts = {}

    def subscribe(self) -> queue.Queue:
        event_queue = queue.Queue()
        with self._lock:
            self._queues.add(event_queue)
        return event_queue

    def subscribe_broadcast(self) -> queue.Queue:
        """Subscribe to broadcasts and replay currently active proactive alerts."""
        event_queue = queue.Queue()
        with self._lock:
            self._queues.add(event_queue)
            for event in self._proactive_alerts.values():
                event_queue.put(event)
        return event_queue

    def unsubscribe(self, event_queue: queue.Queue) -> None:
        with self._lock:
            self._queues.discard(event_queue)

    def bind(self, event_queue: queue.Queue) -> None:
        self._local.queue = event_queue

    def unbind(self) -> None:
        if hasattr(self._local, "queue"):
            del self._local.queue

    def emit(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "data": data}
        target_queue = getattr(self._local, "queue", None)
        if target_queue is not None:
            target_queue.put(event)

    def emit_broadcast(self, event_type: str, data: dict) -> None:
        """Publish a process-wide event to every active SSE subscriber."""
        event = {"type": event_type, "data": data}
        with self._lock:
            alert_key = f"{data.get('type', 'unknown')}:{data.get('mountpoint', '')}"
            if event_type == "alerte_proactive":
                self._proactive_alerts[alert_key] = event
            elif event_type == "alerte_proactive_resolue":
                self._proactive_alerts.pop(alert_key, None)
            queues = tuple(self._queues)
        for event_queue in queues:
            event_queue.put(event)


# ---------------------------------------------------------------------------
# Instance globale partagée entre tous les modules GreatOS
# ---------------------------------------------------------------------------

_global_event_bus: Optional['EventBus'] = None
_bus_lock = threading.Lock()


def get_event_bus() -> 'EventBus':
    """Retourne l'instance globale de l'EventBus (lazy init)."""
    global _global_event_bus
    if _global_event_bus is None:
        with _bus_lock:
            if _global_event_bus is None:
                _global_event_bus = EventBus()
    return _global_event_bus


def register_global_bus(bus: 'EventBus') -> None:
    """Enregistre l'instance bus créée par jarvis/agent.py comme bus global."""
    global _global_event_bus
    with _bus_lock:
        _global_event_bus = bus
