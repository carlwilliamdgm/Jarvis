from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.clap_input import arreter_ecoute_clap, demarrer_ecoute_clap
from jarvis.voice_input import arreter_ecoute_vocale, demarrer_ecoute_vocale
from core.voice_state import get_voice_state


def main() -> None:
    """Lance les écouteurs voix/clap pour un essai matériel local."""
    demarrer_ecoute_vocale()
    demarrer_ecoute_clap()
    print("Écoute active (wake word 'Hey Jarvis' + double-clap). Ctrl+C pour arrêter.")
    try:
        while True:
            print(get_voice_state())
            time.sleep(1)
    except KeyboardInterrupt:
        arreter_ecoute_vocale()
        arreter_ecoute_clap()


if __name__ == "__main__":
    main()
