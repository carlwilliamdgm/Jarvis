"""Affiche les scores openWakeWord locaux sans déclencher Jarvis.

Exécuter depuis la racine du dépôt :
    ./.venv/Scripts/python scripts/calibrer_wakeword.py
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import sounddevice as sd

from jarvis import voice_input


def main() -> None:
    threshold = voice_input._load_wakeword_threshold()
    model = voice_input._new_wake_word_model()
    print(
        f"Calibration active — seuil {threshold:.2f}. "
        "Dites « Hey Jarvis » ; Ctrl+C pour arrêter."
    )
    try:
        with sd.RawInputStream(
            samplerate=voice_input.SAMPLE_RATE,
            blocksize=voice_input.WAKE_WORD_FRAME_LENGTH,
            dtype="int16",
            channels=1,
        ) as stream:
            while True:
                pcm, _overflowed = stream.read(voice_input.WAKE_WORD_FRAME_LENGTH)
                samples = np.frombuffer(bytes(pcm), dtype=np.int16)
                score = model.predict(samples).get("hey_jarvis", 0.0)
                marker = " < DÉTECTÉ" if score >= threshold else ""
                print(f"\rscore hey_jarvis: {score:.3f}{marker}   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nCalibration arrêtée.")


if __name__ == "__main__":
    main()
