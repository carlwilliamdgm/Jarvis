"""État global partagé par les sources d'entrée vocale de Jarvis."""

import json
import os
import threading
from enum import Enum
from pathlib import Path


class VoiceState(str, Enum):
    IDLE = "idle"
    WAKING_UP = "waking_up"  # État intermédiaire pendant la phrase de réveil
    LISTENING = "listening"
    THINKING = "thinking"
    ACTION = "action"        # Exécution d'actions/outils
    SPEAKING = "speaking"
    ERROR = "error"


# Fichier d'état partagé pour l'overlay (process séparé)
VOICE_STATE_FILE = Path(__file__).parent.parent / "voice_state.json"


_voice_state = VoiceState.IDLE
_voice_transcript = ""
_voice_seq = 0
_voice_state_lock = threading.Lock()


def get_voice_state() -> VoiceState:
    """Retourne l'état de la voix de l'instance courante, de façon sûre."""
    with _voice_state_lock:
        return _voice_state


def get_voice_transcript() -> str:
    """Retourne le texte partiel d'écoute affiché par l'overlay."""
    with _voice_state_lock:
        return _voice_transcript


def _snapshot_state() -> tuple[VoiceState, str, int]:
    with _voice_state_lock:
        return _voice_state, _voice_transcript, _voice_seq


def _write_state_to_file():
    """Écrit l'état courant dans le fichier JSON partagé pour l'overlay avec retry sécurisé."""
    import time
    state, transcript, seq = _snapshot_state()
    data = {
        "state": state.value,
        "seq": seq,
        "ts": time.time(),
    }
    if transcript:
        data["text"] = transcript

    tmp_path = VOICE_STATE_FILE.with_name(f"{VOICE_STATE_FILE.name}.{os.getpid()}.tmp")
    for attempt in range(3):
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp_path, VOICE_STATE_FILE)
            break
        except (IOError, OSError):
            if attempt < 2:
                time.sleep(0.005)
            else:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _set_voice_transcript(text: str) -> None:
    """Met à jour le texte d'écoute sans changer l'état."""
    global _voice_transcript, _voice_seq
    cleaned = (text or "").strip()
    with _voice_state_lock:
        if _voice_transcript == cleaned:
            return
        _voice_transcript = cleaned
        _voice_seq += 1
    _write_state_to_file()


def _set_voice_state(state: VoiceState) -> bool:
    """Met à jour l'état global.

    Cycle : IDLE → WAKING_UP → LISTENING → THINKING → ACTION/SPEAKING → LISTENING
    → (parole) LISTENING → … ou (silence 30s) IDLE.

    Un état déjà courant est ignoré (retour ``False``) pour éviter de relire
    l'overlay et de perdre une course entre wake word et double-clap.
    """
    global _voice_state, _voice_transcript, _voice_seq
    with _voice_state_lock:
        if _voice_state is state:
            return False
        _voice_state = state
        _voice_seq += 1
        if state is not VoiceState.LISTENING:
            _voice_transcript = ""
    _write_state_to_file()
    return True
