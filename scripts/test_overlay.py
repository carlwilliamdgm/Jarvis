"""Script de test de l'overlay visuel vocal."""

from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.voice_state import VoiceState, _set_voice_state, get_voice_state
from core.voice_overlay import demarrer_overlay_vocal, arreter_overlay_vocal

def main():
    """Teste l'overlay en simulant les différents états vocaux."""
    print("=== TEST OVERLAY VISUEL VOCAL ===")
    
    print("\n1. Démarrage de l'overlay...")
    demarrer_overlay_vocal()
    print("✓ Overlay démarré")
    time.sleep(1)
    
    print("\n2. Test état LISTENING (ÉCOUTE)...")
    _set_voice_state(VoiceState.LISTENING)
    print(f"État actuel: {get_voice_state()}")
    print("L'overlay devrait apparaître en bas-droite avec 'ÉCOUTE' (cyan)")
    time.sleep(3)
    
    print("\n3. Test état THINKING (RÉFLEXION)...")
    _set_voice_state(VoiceState.THINKING)
    print(f"État actuel: {get_voice_state()}")
    print("L'overlay devrait afficher 'RÉFLEXION' (orange)")
    time.sleep(3)
    
    print("\n4. Test état SPEAKING (PAROLE)...")
    _set_voice_state(VoiceState.SPEAKING)
    print(f"État actuel: {get_voice_state()}")
    print("L'overlay devrait afficher 'PAROLE' (cyan)")
    time.sleep(3)
    
    print("\n5. Test état ERROR (ERREUR)...")
    _set_voice_state(VoiceState.ERROR)
    print(f"État actuel: {get_voice_state()}")
    print("L'overlay devrait afficher 'ERREUR' (rouge)")
    time.sleep(3)
    
    print("\n6. Retour à IDLE (overlay devrait disparaître)...")
    _set_voice_state(VoiceState.IDLE)
    print(f"État actuel: {get_voice_state()}")
    print("L'overlay devrait disparaître")
    time.sleep(2)
    
    print("\n7. Arrêt de l'overlay...")
    arreter_overlay_vocal()
    print("✓ Overlay arrêté")
    
    print("\n=== TEST TERMINÉ ===")
    print("Si vous avez vu l'overlay apparaître et changer d'état, l'overlay fonctionne correctement.")
    print("Le problème est donc que l'état vocal ne change jamais car le microphone ne fonctionne pas.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest interrompu")
        arreter_overlay_vocal()
    except Exception as e:
        print(f"\nErreur: {e}")
        import traceback
        traceback.print_exc()
        arreter_overlay_vocal()
