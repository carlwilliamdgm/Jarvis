"""Script pour tester tous les microphones disponibles."""

from pathlib import Path
import sys
import numpy as np
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd

def test_all_microphones():
    """Teste tous les microphones disponibles."""
    devices = sd.query_devices()
    
    print("=== TEST DE TOUS LES MICROPHONES ===")
    print(f"{len(devices)} périphériques détectés\n")
    
    results = []
    
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            print(f"--- Microphone {i}: {device['name']} ---")
            print(f"  Entrées: {device['max_input_channels']}")
            print(f"  Sorties: {device['max_output_channels']}")
            print(f"  Taux d'échantillonnage par défaut: {device['default_samplerate']}")
            
            try:
                # Test d'enregistrement avec ce périphérique
                print(f"  Test d'enregistrement...")
                with sd.RawInputStream(device=i, samplerate=16000, dtype="int16", channels=1) as stream:
                    data, _ = stream.read(16000)  # 1 seconde
                    samples = np.frombuffer(bytes(data), dtype=np.int16)
                    max_amplitude = np.max(np.abs(samples))
                    mean_amplitude = np.mean(np.abs(samples))
                    
                    print(f"  ✓ Amplitude max: {max_amplitude}")
                    print(f"  ✓ Amplitude moyenne: {mean_amplitude:.2f}")
                    
                    if max_amplitude > 1000:
                        print(f"  ✓✓ MICROPHONE FONCTIONNEL")
                        results.append((i, device['name'], max_amplitude))
                    elif max_amplitude > 100:
                        print(f"  ⚠ Amplitude faible mais utilisable")
                        results.append((i, device['name'], max_amplitude))
                    else:
                        print(f"  ✗ Amplitude trop faible")
                    
            except Exception as e:
                print(f"  ✗ Erreur: {e}")
            
            print()
    
    print("=== RÉSUMÉ ===")
    if results:
        print("Microphones fonctionnels détectés:")
        for device_id, name, amplitude in sorted(results, key=lambda x: -x[2]):
            print(f"  ID {device_id}: {name} (amplitude: {amplitude})")
        
        print(f"\nMeilleur microphone: ID {results[0][0]} - {results[0][1]}")
        print(f"\nPour utiliser ce microphone, définissez:")
        print(f"  sd.default.device = ({results[0][0]}, {sd.default.device[1]})")
    else:
        print("Aucun microphone fonctionnel détecté.")
        print("Vérifiez:")
        print("  - Les paramètres audio Windows")
        print("  - Que le microphone n'est pas muet")
        print("  - Les permissions d'accès microphone")

if __name__ == "__main__":
    test_all_microphones()
