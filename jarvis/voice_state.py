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
VOICE_STATE_FILE = Path(__file__).resolve().parent.parent / "runtime" / "voice_state.json"


_voice_state = VoiceState.IDLE
_voice_transcript = ""
_voice_audio_input: dict[str, object] = {"available": False, "device": None, "reason": "not_initialized"}
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


def _snapshot_state() -> tuple[VoiceState, str, dict[str, object], int]:
    with _voice_state_lock:
        return _voice_state, _voice_transcript, dict(_voice_audio_input), _voice_seq


def _write_state_to_file():
    """Écrit l'état courant dans le fichier JSON partagé pour l'overlay avec retry sécurisé."""
    import time
    state, transcript, audio_input, seq = _snapshot_state()
    data = {
        "state": state.value,
        "seq": seq,
        "ts": time.time(),
        "audio_input": audio_input,
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
    if cleaned:
        try:
            from interface_morphique import hud_controller
            hud_controller.dire_vous(cleaned)
        except Exception:
            pass


def _set_voice_audio_input(status: dict[str, object]) -> None:
    """Publie au HUD l'état du microphone fourni par l'OS hôte."""
    global _voice_audio_input, _voice_seq
    normalized = {
        "available": bool(status.get("available")),
        "device": status.get("device"),
        "reason": status.get("reason"),
    }
    with _voice_state_lock:
        if _voice_audio_input == normalized:
            return
        _voice_audio_input = normalized
        _voice_seq += 1
    _write_state_to_file()


def _set_voice_state(state: VoiceState) -> bool:
    """Met à jour l'état global.

    Cycle : IDLE → WAKING_UP → LISTENING → THINKING → ACTION/SPEAKING → LISTENING
    → (parole) LISTENING → … ou (silence 25s) IDLE.

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
    try:
        from interface_morphique import hud_controller
        etat_map = {
            VoiceState.IDLE: "veille",
            VoiceState.WAKING_UP: "ecoute",
            VoiceState.LISTENING: "ecoute",
            VoiceState.THINKING: "reflexion",
            VoiceState.ACTION: "reflexion",
            VoiceState.SPEAKING: "parole",
            VoiceState.ERROR: "veille",
        }
        hud_controller.etat(etat_map.get(state, "veille"))
        if state is VoiceState.WAKING_UP:
            hud_controller.mettre_au_premier_plan()
    except Exception:
        pass
    return True
