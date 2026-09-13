"""Script de test de l'overlay visuel vocal."""

from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.voice_state import VoiceState, _set_voice_state, get_voice_state
from jarvis.voice_overlay import demarrer_overlay_vocal, arreter_overlay_vocal

def main():
    """Teste l'overlay en simulant le cycle complet spécifié par l'utilisateur."""
    from jarvis.voice_state import _set_voice_transcript
    print("=== TEST OVERLAY VISUEL VOCAL - CYCLE COMPLET ===")
    
    print("\n1. Démarrage de l'overlay...")
    demarrer_overlay_vocal()
    print("✓ Overlay démarré (actuellement IDLE, donc invisible)")
    time.sleep(1.5)
    
    print("\n2. Test RÉVEIL (ondes radar dorées)...")
    _set_voice_state(VoiceState.WAKING_UP)
    print(f"État actuel: {get_voice_state()} - Animation or")
    time.sleep(2.5)

    print("\n3. Test ÉCOUTE (visualiseur cyan + transcription dynamique)...")
    _set_voice_state(VoiceState.LISTENING)
    _set_voice_transcript("bonjour")
    time.sleep(1.0)
    _set_voice_transcript("bonjour jarvis")
    time.sleep(1.0)
    _set_voice_transcript("bonjour jarvis quelle heure est il")
    print(f"État actuel: {get_voice_state()} - Écoute active avec texte")
    time.sleep(1.5)
    
    print("\n4. Test RÉFLEXION (orbital spinner orange)...")
    _set_voice_state(VoiceState.THINKING)
    print(f"État actuel: {get_voice_state()} - Spinner en rotation")
    time.sleep(2.5)

    print("\n5. Test ACTION (indicateur action violet)...")
    _set_voice_state(VoiceState.ACTION)
    print(f"État actuel: {get_voice_state()} - Action en cours")
    time.sleep(2.0)
    
    print("\n6. Test PAROLE (égaliseur sonore cyan)...")
    _set_voice_state(VoiceState.SPEAKING)
    print(f"État actuel: {get_voice_state()} - Synthèse vocale")
    time.sleep(2.5)

    print("\n7. Test retour ÉCOUTE (fenêtre 30s)...")
    _set_voice_state(VoiceState.LISTENING)
    print(f"État actuel: {get_voice_state()} - Prêt pour le prochain énoncé")
    time.sleep(2.0)
    
    print("\n8. Test IDLE (overlay doit redevenir invisible)...")
    _set_voice_state(VoiceState.IDLE)
    print(f"État actuel: {get_voice_state()} - Overlay masqué")
    time.sleep(1.5)
    
    print("\n9. Arrêt de l'overlay...")
    arreter_overlay_vocal()
    print("✓ Overlay arrêté")
    print("\n=== TEST DU CYCLE TERMINÉ AVEC SUCCÈS ===")

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
