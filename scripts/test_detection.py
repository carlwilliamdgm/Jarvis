"""Script de test de détection avec différents seuils."""

from pathlib import Path
import sys
import time
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd
from openwakeword.model import Model
from capabilities.clap_input import DoubleClapDetector, _maximum_amplitude, CLAP_AMPLITUDE_THRESHOLD

def test_wakeword_detection():
    """Teste la détection du wake word avec différents seuils."""
    print("=== TEST DÉTECTION WAKE WORD ===")
    
    model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    print("Modèle wake word chargé")
    
    print("\nTest avec différents seuils de détection (parlez 'Hey Jarvis')...")
    print("Appuyez sur Ctrl+C pour arrêter\n")
    
    with sd.RawInputStream(device=1, samplerate=16000, blocksize=1280, dtype="int16", channels=1) as stream:
        max_score = 0.0
        start_time = time.monotonic()
        
        try:
            while time.monotonic() - start_time < 30:  # 30 secondes de test
                data, _ = stream.read(1280)
                samples = np.frombuffer(bytes(data), dtype=np.int16)
                scores = model.predict(samples)
                score = scores.get("hey_jarvis", 0.0)
                max_score = max(max_score, score)
                
                if score > 0.1:  # Afficher les scores significatifs
                    print(f"Score détecté: {score:.3f} (max: {max_score:.3f})")
                
                if score >= 0.5:
                    print(f"✓✓ WAKE WORD DÉTECTÉ avec seuil 0.5! Score: {score:.3f}")
                    return True
                elif score >= 0.3:
                    print(f"⚠ Score élevé avec seuil 0.3: {score:.3f}")
                elif score >= 0.2:
                    print(f"⚠ Score modéré avec seuil 0.2: {score:.3f}")
                
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            print("\nTest interrompu")
        
        print(f"\nScore maximum atteint: {max_score:.3f}")
        if max_score < 0.1:
            print("⚠ Aucune détection significative - le modèle peut ne pas reconnaître votre voix")
            print("  Essayez de parler plus fort ou plus clairement")
        elif max_score < 0.3:
            print("⚠ Détection faible - essayez de baisser le seuil à 0.2")
        elif max_score < 0.5:
            print("⚠ Détection modérée - essayez de baisser le seuil à 0.3")
        
        return False

def test_clap_detection():
    """Teste la détection de double-clap."""
    print("\n=== TEST DÉTECTION DOUBLE-CLAP ===")
    
    detector = DoubleClapDetector()
    print(f"Seuil de détection: {CLAP_AMPLITUDE_THRESHOLD}")
    print("Faites des double-claps (appuyez sur Ctrl+C pour arrêter)\n")
    
    with sd.RawInputStream(device=1, samplerate=16000, blocksize=800, dtype="int16", channels=1) as stream:
        max_amplitude = 0
        start_time = time.monotonic()
        
        try:
            while time.monotonic() - start_time < 30:  # 30 secondes de test
                data, _ = stream.read(800)
                amplitude = _maximum_amplitude(bytes(data))
                max_amplitude = max(max_amplitude, amplitude)
                
                if amplitude > 1000:
                    print(f"Amplitude: {amplitude}")
                
                if detector.process_peak(amplitude, time.monotonic()):
                    print(f"✓✓ DOUBLE-CLAP DÉTECTÉ! Amplitude: {amplitude}")
                    return True
                
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            print("\nTest interrompu")
        
        print(f"\nAmplitude maximum: {max_amplitude}")
        if max_amplitude < CLAP_AMPLITUDE_THRESHOLD:
            print(f"⚠ Amplitude trop faible ({max_amplitude} < {CLAP_AMPLITUDE_THRESHOLD})")
            print("  Les claps sont peut-être trop faibles ou trop loin du microphone")
        else:
            print("✓ Amplitude suffisante pour détection")
        
        return False

def main():
    """Exécute les tests de détection."""
    print("TESTS DE DÉTECTION VOCALE JARVIS")
    print("=" * 50)
    
    print("\nConseils:")
    print("- Pour le wake word: Parlez clairement 'Hey Jarvis' à proximité du micro")
    print("- Pour le double-clap: Faites deux claps nets et espacés de 0.2-0.8 secondes")
    print()
    
    # Test wake word
    wakeword_ok = test_wakeword_detection()
    
    # Test clap
    clap_ok = test_clap_detection()
    
    print("\n" + "=" * 50)
    print("RÉSUMÉ:")
    if wakeword_ok:
        print("✓ Wake word fonctionnel")
    else:
        print("✗ Wake word non détecté - ajustez le seuil ou la prononciation")
    
    if clap_ok:
        print("✓ Double-clap fonctionnel")
    else:
        print("✗ Double-clap non détecté - ajustez le seuil ou l'intensité")

if __name__ == "__main__":
    main()
