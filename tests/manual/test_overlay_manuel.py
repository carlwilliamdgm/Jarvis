"""Test manuel de l'overlay vocal - Simule les transitions d'état."""

import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from core.voice_state import VoiceState, _set_voice_state

def test_overlay_transitions():
    """Test manuel des transitions d'état pour l'overlay."""
    print("=== Test manuel Overlay Vocal ===")
    print("Ouvrez une application (navigateur/éditeur) et gardez le focus dessus.")
    print("L'overlay devrait apparaître en bas-droite lors des états actifs.\n")
    print("Début du test dans 3 secondes...")
    time.sleep(3)
    
    print("\n1. Transition IDLE -> LISTENING")
    print("   Overlay devrait apparaître avec 'ÉCOUTE' (cyan)")
    _set_voice_state(VoiceState.LISTENING)
    time.sleep(3)
    
    print("\n2. Transition LISTENING -> THINKING")
    print("   Overlay devrait passer en 'RÉFLEXION' (orange)")
    _set_voice_state(VoiceState.THINKING)
    time.sleep(3)
    
    print("\n3. Transition THINKING -> SPEAKING")
    print("   Overlay devrait passer en 'PAROLE' (cyan)")
    _set_voice_state(VoiceState.SPEAKING)
    time.sleep(3)
    
    print("\n4. Transition SPEAKING -> ERROR")
    print("   Overlay devrait passer en 'ERREUR' (rouge)")
    _set_voice_state(VoiceState.ERROR)
    time.sleep(3)
    
    print("\n5. Transition ERROR -> IDLE")
    print("   Overlay devrait disparaître")
    _set_voice_state(VoiceState.IDLE)
    time.sleep(2)
    
    print("\n=== Test terminé ===")
    print("Vérifiez que :")
    print("- L'overlay est apparu dès LISTENING")
    print("- Les transitions de couleur/libellé étaient correctes")
    print("- L'overlay a disparu au retour à IDLE")
    print("- Les clics passaient à travers (cliquez sur votre application pendant le test)")

if __name__ == "__main__":
    test_overlay_transitions()