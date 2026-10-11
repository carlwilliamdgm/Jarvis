"""Démon conversationnel temps réel pour Jarvis (GreatOS).

Fonctionnalités :
- Déclenchement fluide par 'Jarvis', 'Hey Jarvis', 'Dis Jarvis', ou directement 'Regarde mon écran'.
- Mode CONVERSATION CONTINUE (15 secondes) : une fois activé, pas besoin de répéter 'Jarvis'.
- Vision d'écran automatique dès qu'on mentionne l'écran ou une erreur.
- Réponses vocales naturelles garanties (Edge-TTS Henri).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("Jarvis")

import numpy as np
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from jarvis.audio_capture import get_audio_capture_engine
from jarvis.voice_output_edge import synthetiser_et_jouer
from jarvis.voice_input import transcrire_audio_pcm
from datashield.confirmations import use_voice_confirmation
import jarvis


# Mots-clés déclencheurs et variantes phonétiques
DECLENCHEURS_JARVIS = (
    "jarvis", "jervis", "j'envisse", "envisse", "djarvis",
    "service", "dis jarvis", "hey jarvis", "ok jarvis",
    "regarde mon écran", "regarde l'écran", "analyse mon écran"
)

def contient_declencheur(texte: str) -> bool:
    t = texte.lower()
    return any(d in t for d in DECLENCHEURS_JARVIS)


def main():
    print("\n" + "=" * 65)
    print("  J.A.R.V.I.S. — INTERFACE TEMPS RÉEL INTERACTIVE")
    print("=" * 65)
    print("  • Dites simplement : 'Jarvis' ou directement votre consigne.")
    print("  • Exemples : 'Jarvis, regarde mon écran', 'Jarvis, il est quelle heure ?'")
    print("  • Mode conversation continue actif (15s d'écoute après chaque échange).")
    print("  • Quitter : Ctrl + C")
    print("=" * 65 + "\n")

    engine = get_audio_capture_engine()
    if not engine.ouvrir():
        LOGGER.error("Impossible d'ouvrir le micro.")
        return

    memoire = jarvis.initialiser()
    historique = []

    # Salutation initiale
    synthetiser_et_jouer("À votre service, monsieur. Je vous écoute.")
    LOGGER.info("En écoute...")

    # Seuil d'énergie de détection vocale (650 évite de capter la TV au fond de la pièce)
    SEUIL_ENERGIE_VOIX = int(os.getenv("JARVIS_VOICE_ENERGY_THRESHOLD", "650"))
    SILENCE_MAX_TRAMES = 8  # ~500 ms de silence pour finaliser la prise de parole

    # Gestion de la conversation active (fenêtre de 15 secondes sans devoir répéter 'Jarvis')
    derniere_interaction = 0.0
    DELAI_CONVERSATION_ACTIVE = 15.0

    from jarvis.wake_word_local import detecter_wakeword_local

    # Brancher la confirmation vocale : toute action sensible sera posée à voix
    # haute — aucun input() clavier ne sera jamais sollicité dans le démon.
    with use_voice_confirmation(engine, synthetiser_et_jouer, transcrire_audio_pcm):
        try:
            while True:
                frame = engine.lire_depuis_queue("wake", timeout=0.1)
                if frame is None or not hasattr(frame, "samples"):
                    continue

                amp = int(np.max(np.abs(frame.samples)))

                # Détection de voix
                if amp > SEUIL_ENERGIE_VOIX:
                    morceaux = [bytes(frame.samples)]
                    silence_consecutif = 0

                    # Capturer l'énoncé complet
                    for _ in range(65):  # Jusqu'à 5 secondes max
                        trame = engine.lire_depuis_queue("wake", timeout=0.08)
                        if trame and hasattr(trame, "samples"):
                            morceaux.append(bytes(trame.samples))
                            trame_amp = int(np.max(np.abs(trame.samples)))
                            if trame_amp > SEUIL_ENERGIE_VOIX:
                                silence_consecutif = 0
                            else:
                                silence_consecutif += 1
                                if silence_consecutif >= SILENCE_MAX_TRAMES:
                                    break
                        time.sleep(0.06)

                    full_pcm = b"".join(morceaux)
                    maintenant = time.time()
                    en_conversation = (maintenant - derniere_interaction) < DELAI_CONVERSATION_ACTIVE

                    # FILTRE ANTI-PARASITES (TV / bruits ambiants) :
                    # Si on n'est pas déjà en conversation active, vérifier localement
                    # en <50ms que l'énoncé contient un déclencheur avant d'appeler Groq.
                    if not en_conversation and not detecter_wakeword_local(full_pcm):
                        continue

                    # Groq Whisper en préférence, Vosk local si le cloud échoue.
                    texte = transcrire_audio_pcm(full_pcm)

                    if not texte or len(texte.strip()) < 2:
                        continue

                    LOGGER.info(f"👤 Vous : {texte}")

                    # Accepter si le mot 'Jarvis' est présent OU si la conversation est déjà active
                    if contient_declencheur(texte) or en_conversation:
                        derniere_interaction = time.time()

                        # Nettoyer l'appel pour ne garder que la consigne
                        texte_epure = re.sub(r'\b(hey|dis|ok)?\s*(jarvis|jervis|djarvis)\b', '', texte, flags=re.IGNORECASE).strip(" ,.?!")

                        if not texte_epure:
                            # Si vous avez juste dit "Jarvis"
                            LOGGER.info("🤖 Jarvis : Oui, monsieur ?")
                            synthetiser_et_jouer("Oui, monsieur ?")
                            engine.drainer_et_ignorer_garde(300)
                            continue

                        # Toute intention passe par Jarvis : politique DataShield,
                        # confirmations vocales et outils propriétaires compris.
                        LOGGER.info("🧠 Traitement...")
                        res = jarvis.executer_interaction_utilisateur(
                            texte_epure or texte,
                            historique,
                            memoire,
                            ignorer_si_occupe=False,
                            origine_vocale=False,
                        )
                        if isinstance(res, tuple):
                            reponse_texte = str(res[0])
                        elif isinstance(res, dict):
                            reponse_texte = str(res.get("reponse", ""))
                        else:
                            reponse_texte = str(res or "")

                        if reponse_texte:
                            LOGGER.info(f"🤖 Jarvis : {reponse_texte}")
                            synthetiser_et_jouer(reponse_texte)
                            derniere_interaction = time.time()

                        engine.drainer_et_ignorer_garde(400)
                        LOGGER.info("En écoute (conversation active pendant 15s)...")

        except KeyboardInterrupt:
            LOGGER.info("Fermeture.")
        finally:
            engine.fermer()


if __name__ == "__main__":
    main()
