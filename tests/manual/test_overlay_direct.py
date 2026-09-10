"""Test direct de l'overlay sans passer par uvicorn."""

import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
import threading
from jarvis.voice_state import VoiceState, _set_voice_state
from jarvis.voice_overlay import VoiceOverlay

def test_overlay_direct():
    """Test direct de l'overlay sans uvicorn."""
    print("=== Test direct Overlay ===")
    
    # Créer et démarrer l'overlay
    overlay = VoiceOverlay()
    overlay.start()
    
    print("Overlay démarré, début des transitions dans 2 secondes...")
    time.sleep(2)
    
    print("\n1. IDLE -> LISTENING")
    _set_voice_state(VoiceState.LISTENING)
    time.sleep(3)
    
    print("2. LISTENING -> THINKING")
    _set_voice_state(VoiceState.THINKING)
    time.sleep(3)
    
    print("3. THINKING -> SPEAKING")
    _set_voice_state(VoiceState.SPEAKING)
    time.sleep(3)
    
    print("4. SPEAKING -> ERROR")
    _set_voice_state(VoiceState.ERROR)
    time.sleep(3)
    
    print("5. ERROR -> IDLE")
    _set_voice_state(VoiceState.IDLE)
    time.sleep(2)
    
    overlay.stop()
    print("=== Test terminé ===")

if __name__ == "__main__":
    test_overlay_direct()