"""État global partagé par les sources d'entrée vocale de Jarvis."""

from enum import Enum
import threading


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


_voice_state = VoiceState.IDLE
_voice_state_lock = threading.Lock()


def get_voice_state() -> VoiceState:
    """Retourne l'état de la voix de l'instance courante, de façon sûre."""
    with _voice_state_lock:
        return _voice_state


def _set_voice_state(state: VoiceState) -> bool:
    """Met à jour l'état global.

    ``LISTENING`` est réservé au premier déclencheur arrivé : il ne peut
    commencer que depuis ``IDLE``. Les autres transitions de cette mission
    sont volontairement directes.
    """
    global _voice_state
    with _voice_state_lock:
        if state is VoiceState.LISTENING and _voice_state is not VoiceState.IDLE:
            return False
        _voice_state = state
        return True
