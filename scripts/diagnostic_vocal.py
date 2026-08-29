"""Script de diagnostic détaillé pour l'interface vocale."""

from pathlib import Path
import sys
import time
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def test_dependencies():
    """Teste les dépendances vocales."""
    print("=== TEST DES DÉPENDANCES ===")
    
    try:
        import sounddevice as sd
        print("✓ sounddevice installé")
    except ImportError as e:
        print(f"✗ sounddevice manquant: {e}")
        return False
    
    try:
        import vosk
        print("✓ vosk installé")
    except ImportError as e:
        print(f"✗ vosk manquant: {e}")
        return False
    
    try:
        import openwakeword
        print("✓ openwakeword installé")
    except ImportError as e:
        print(f"✗ openwakeword manquant: {e}")
        return False
    
    try:
        import piper_tts
        print("✓ piper-tts installé")
    except ImportError as e:
        print(f"✗ piper-tts manquant: {e}")
        return False
    
    return True

def test_microphone():
    """Teste l'accès au microphone."""
    print("\n=== TEST MICROPHONE ===")
    
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print(f"✓ {len(devices)} périphériques audio détectés")
        
        # Trouver le périphérique d'entrée par défaut
        default_input = sd.default.device[0]
        print(f"✓ Périphérique d'entrée par défaut: {devices[default_input]['name']}")
        
        # Test d'enregistrement court
        print("Test d'enregistrement de 1 seconde...")
        with sd.RawInputStream(samplerate=16000, dtype="int16", channels=1) as stream:
            data, _ = stream.read(16000)
            samples = np.frombuffer(bytes(data), dtype=np.int16)
            max_amplitude = np.max(np.abs(samples))
            print(f"✓ Enregistrement OK, amplitude max: {max_amplitude}")
            
            if max_amplitude < 100:
                print("⚠ Amplitude très faible - microphone可能 muet ou mal configuré")
            else:
                print(f"✓ Microphone actif (amplitude: {max_amplitude})")
        
        return True
    except Exception as e:
        print(f"✗ Erreur microphone: {e}")
        return False

def test_vosk_models():
    """Teste les modèles Vosk."""
    print("\n=== TEST MODÈLES VOSK ===")
    
    try:
        from capabilities.voice_input import _model_path, get_vosk_model
        import os
        
        # Test français
        fr_path = _model_path("fr")
        if fr_path.exists():
            print(f"✓ Modèle français trouvé: {fr_path}")
        else:
            print(f"✗ Modèle français manquant: {fr_path}")
        
        # Test anglais
        en_path = _model_path("en")
        if en_path.exists():
            print(f"✓ Modèle anglais trouvé: {en_path}")
        else:
            print(f"✗ Modèle anglais manquant: {en_path}")
        
        # Test chargement
        model = get_vosk_model()
        print("✓ Modèle Vosk chargé avec succès")
        
        return True
    except Exception as e:
        print(f"✗ Erreur modèles Vosk: {e}")
        return False

def test_wakeword():
    """Teste le wake word."""
    print("\n=== TEST WAKE WORD ===")
    
    try:
        from openwakeword.model import Model
        
        print("Chargement du modèle hey_jarvis...")
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        print("✓ Modèle wake word chargé")
        
        # Test avec silence
        samples = np.zeros(1280, dtype=np.int16)
        scores = model.predict(samples)
        print(f"✓ Test silence OK: {scores}")
        
        # Test avec bruit aléatoire
        noise = np.random.randint(-1000, 1000, 1280, dtype=np.int16)
        scores = model.predict(noise)
        print(f"✓ Test bruit OK: {scores}")
        
        return True
    except Exception as e:
        print(f"✗ Erreur wake word: {e}")
        return False

def test_clap_detection():
    """Teste la détection de clap."""
    print("\n=== TEST DÉTECTION CLAP ===")
    
    try:
        from capabilities.clap_input import DoubleClapDetector, CLAP_AMPLITUDE_THRESHOLD
        
        print(f"Seuil de détection: {CLAP_AMPLITUDE_THRESHOLD}")
        detector = DoubleClapDetector()
        
        # Test avec amplitude faible
        result = detector.process_peak(100, time.monotonic())
        print(f"✓ Test amplitude faible (100): {result} (attendu: False)")
        
        # Test avec amplitude élevée
        result = detector.process_peak(15000, time.monotonic())
        print(f"✓ Test amplitude élevée (15000): {result} (attendu: False - premier pic)")
        
        # Test double clap simulé
        detector._first_peak_at = time.monotonic() - 0.3
        result = detector.process_peak(15000, time.monotonic())
        print(f"✓ Test double clap simulé: {result} (attendu: True)")
        
        return True
    except Exception as e:
        print(f"✗ Erreur détection clap: {e}")
        return False

def test_full_pipeline():
    """Teste le pipeline complet avec enregistrement réel."""
    print("\n=== TEST PIPELINE COMPLET ===")
    print("Parlez maintenant ou faites un clap (10 secondes)...")
    
    try:
        import sounddevice as sd
        from openwakeword.model import Model
        from capabilities.clap_input import DoubleClapDetector, _maximum_amplitude, CLAP_AMPLITUDE_THRESHOLD
        
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        detector = DoubleClapDetector()
        
        wake_word_detected = False
        clap_detected = False
        max_amplitude = 0
        
        with sd.RawInputStream(samplerate=16000, blocksize=1280, dtype="int16", channels=1) as stream:
            start_time = time.monotonic()
            while time.monotonic() - start_time < 10:
                data, _ = stream.read(1280)
                samples = np.frombuffer(bytes(data), dtype=np.int16)
                
                # Test amplitude
                current_max = _maximum_amplitude(bytes(data))
                max_amplitude = max(max_amplitude, current_max)
                
                # Test wake word
                scores = model.predict(samples)
                if scores.get("hey_jarvis", 0.0) >= 0.5:
                    wake_word_detected = True
                    print(f"✓ Wake word détecté! Score: {scores['hey_jarvis']}")
                    break
                
                # Test clap
                if detector.process_peak(current_max, time.monotonic()):
                    clap_detected = True
                    print(f"✓ Double clap détecté! Amplitude: {current_max}")
                    break
        
        print(f"Amplitude maximale enregistrée: {max_amplitude}")
        print(f"Seuil de clap: {CLAP_AMPLITUDE_THRESHOLD}")
        
        if wake_word_detected:
            print("✓ Wake word détecté pendant le test")
        elif clap_detected:
            print("✓ Double clap détecté pendant le test")
        elif max_amplitude < CLAP_AMPLITUDE_THRESHOLD:
            print(f"⚠ Amplitude trop faible ({max_amplitude} < {CLAP_AMPLITUDE_THRESHOLD})")
            print("  Vérifiez que le microphone fonctionne et n'est pas muet")
        else:
            print("⚠ Aucune détection - essayez de parler plus fort ou de faire des claps plus net")
        
        return True
    except Exception as e:
        print(f"✗ Erreur pipeline: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Exécute tous les tests."""
    print("DIAGNOSTIC INTERFACE VOCALE JARVIS")
    print("=" * 50)
    
    all_ok = True
    all_ok &= test_dependencies()
    all_ok &= test_microphone()
    all_ok &= test_vosk_models()
    all_ok &= test_wakeword()
    all_ok &= test_clap_detection()
    
    if all_ok:
        print("\n" + "=" * 50)
        print("Tests de base OK. Lancement du test pipeline...")
        print("=" * 50)
        test_full_pipeline()
    else:
        print("\n" + "=" * 50)
        print("Certains tests de base ont échoué.")
        print("Corrigez les erreurs avant de continuer.")
        print("=" * 50)

if __name__ == "__main__":
    main()
