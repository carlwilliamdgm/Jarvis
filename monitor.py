#monitor.py

import time

from capabilities.storage import (
    INTERVALLE,
    SEUIL_CRITIQUE,
    SEUIL_ORANGE,
    SEUIL_ROUGE,
    audit_stockage,
    get_stockage,
    notifier,
    top_fichiers_lourds,
)


def surveiller():
    print("[Jarvis] Surveillance du stockage demarree.")
    while True:
        libre = get_stockage()
        print(f"[Jarvis] Stockage libre : {libre}%")

        if libre <= SEUIL_CRITIQUE:
            notifier("CRITIQUE", f"Seulement {libre}% libre !", urgence=True)
            print(audit_stockage())
            print(top_fichiers_lourds())
        elif libre <= SEUIL_ROUGE:
            notifier("Stockage bas", f"{libre}% libre - action recommandee.", urgence=True)
            print(audit_stockage())
        elif libre <= SEUIL_ORANGE:
            notifier("Stockage bas", f"{libre}% libre - surveille.", urgence=False)

        time.sleep(INTERVALLE)


if __name__ == "__main__":
    surveiller()
