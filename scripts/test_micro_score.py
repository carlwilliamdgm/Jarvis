"""Test en direct du score Wake Word et du volume du micro.
Affiche chaque seconde le niveau audio et le score 'hey_jarvis'.
"""
import os, sys, time
import numpy as np
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis.audio_capture import get_audio_capture_engine
from jarvis.voice_input import _new_wake_word_model

engine = get_audio_capture_engine()
engine.ouvrir()
model = _new_wake_word_model()

print("\n" + "=" * 60)
print("  TEST MICRO EN DIRECT — PARLEZ MAINTENANT !")
print("  Dites 'Jarvis' ou parlez normalement dans le micro.")
print("  Appuyez sur Ctrl+C pour arrêter.")
print("=" * 60 + "\n")

try:
    max_score = 0.0
    while True:
        frame = engine.lire_depuis_queue("wake", timeout=0.1)
        if frame and hasattr(frame, "samples"):
            samples = frame.samples
            amp = int(np.max(np.abs(samples)))
            scores = model.predict(samples)
            score = scores.get("hey_jarvis", 0.0)
            max_score = max(max_score, score)

            bar = "#" * int(score * 40)
            status = "⚡ DETECTÉ !" if score >= 0.3 else ""
            print(f"Volume: {amp:5d} | Score 'hey_jarvis': {score:.3f} | Max: {max_score:.3f} | {bar} {status}")
        time.sleep(0.08)
except KeyboardInterrupt:
    print(f"\nScore maximal atteint pendant le test : {max_score:.3f}")
finally:
    engine.fermer()
