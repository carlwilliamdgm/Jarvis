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
from jarvis.voice_transcription import transcrire_audio_groq
from core_intellect.screen_vision import analyser_ecran_actuel
from datashield.confirmations import use_voice_confirmation
import jarvis


# Mots-clés déclencheurs et variantes phonétiques
DECLENCHEURS_JARVIS = (
    "jarvis", "jervis", "j'envisse", "envisse", "djarvis",
    "service", "dis jarvis", "hey jarvis", "ok jarvis",
    "regarde mon écran", "regarde l'écran", "analyse mon écran"
)

# Mots-clés déclenchant la vision
DECLENCHEURS_VISION = (
    "regarde", "écran", "ecran", "vois-tu", "vois tu",
    "analyse ce", "analyse cette", "cette erreur", "ce code",
    "qu'est-ce qu'il y a", "qu'y a-t-il", "aide-moi avec ce"
)


def contient_declencheur(texte: str) -> bool:
    t = texte.lower()
    return any(d in t for d in DECLENCHEURS_JARVIS)


def est_demande_vision(texte: str) -> bool:
    t = texte.lower()
    return any(v in t for v in DECLENCHEURS_VISION)


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
    with use_voice_confirmation(engine, synthetiser_et_jouer, transcrire_audio_groq):
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

                    # Transcription haute vitesse via Groq Whisper
                    texte = transcrire_audio_groq(full_pcm)

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

                        # Traitement vision d'écran vs Actions Windows directes vs LLM général
                        texte_low = texte.lower()
                        if est_demande_vision(texte):
                            LOGGER.info("👁️ Analyse de votre écran en cours...")
                            reponse_texte = analyser_ecran_actuel(texte)
                        elif any(w in texte_low for w in ["monte le son", "monte le volume", "baisse le son", "baisse le volume", "coupe le son", "remets le son"]):
                            from taskflow.windows_actions import controler_volume
                            reponse_texte = controler_volume(texte_low)
                        elif any(w in texte_low for w in ["pause", "mets en pause", "reprends la lecture", "musique suivante", "piste suivante"]):
                            from taskflow.windows_actions import controler_media
                            reponse_texte = controler_media(texte_low)
                        elif any(w in texte_low for w in ["ouvre vs code", "ouvre vscode", "ouvre le code", "ouvre le projet"]):
                            from taskflow.windows_actions import lancer_application
                            reponse_texte = lancer_application("vscode")
                        elif any(w in texte_low for w in ["ouvre le terminal", "ouvre la console", "ouvre powershell"]):
                            from taskflow.windows_actions import lancer_application
                            reponse_texte = lancer_application("terminal")
                        elif any(w in texte_low for w in ["ouvre l'explorateur", "ouvre le dossier"]):
                            from taskflow.windows_actions import lancer_application
                            reponse_texte = lancer_application("explorateur")
                        elif any(w in texte_low for w in ["minimise tout", "affiche le bureau", "montre le bureau"]):
                            from taskflow.windows_actions import minimiser_tout
                            reponse_texte = minimiser_tout()
                        elif any(w in texte_low for w in ["verrouille le pc", "verrouille l'ordinateur", "verrouille mon pc"]):
                            from taskflow.windows_actions import verrouiller_poste
                            reponse_texte = verrouiller_poste()
                        else:
                            LOGGER.info("🧠 Traitement...")
                            res = jarvis.executer_interaction_utilisateur(
                                texte, historique, memoire, ignorer_si_occupe=False, origine_vocale=True
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
