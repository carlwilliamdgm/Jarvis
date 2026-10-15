"""Filtrage des hallucinations et nettoyage des transcriptions pour Jarvis.

Élimine les transcriptions parasites générées par Whisper ou Vosk sur du
silence, du bruit de fond ou des résidus de détection du wake word.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Phrases que Whisper invente fréquemment sur du silence, de la musique ou du bruit blanc.
HALLUCINATIONS = (
    "amara.org",
    "sous-titres",
    "sous titres",
    "merci d'avoir regarde",
    "merci d'avoir visionne",
    "merci d'avoir suivi",
    "merci de m'avoir ecoute",
    "merci pour votre attention",
    "abonnez-vous",
    "abonnez vous",
    "a la prochaine video",
    "a bientot pour une nouvelle video",
    "n'oubliez pas de vous abonner",
    "sous-titrage",
    "sous-titres realises par",
    "transcription :",
    "transcription par",
    "bonne journee a tous",
    "au revoir et a bientot",
    "regardez la video",
    "likez et partagez",
    "pouce bleu",
    "musique",
    "[musique]",
    "(musique)",
    "whisper",
    "translated by",
    "subtitles by",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "don't forget to subscribe",
    "see you next time",
    "bye bye",
)

# Résidus fréquents de wake word captés en tout début d'énoncé
RESIDUS_WAKE_WORD = (
    "avis",
    "service",
    "jarvis",
    "hey jarvis",
    "harvis",
    "arvis",
    "javis",
    "charvis",
    "chavis",
    "davis",
    "y a vis",
    "a vis",
    "la vis",
    "et vis",
    "ervice",
    "servi",
    "sers vis",
    "dis jarvis",
    "dis-moi jarvis",
    "ok jarvis",
)

# Mots ou sons parasites isolés qui ne constituent pas une commande
MOTS_PARASITES_ISOLES = {
    "ah", "oh", "euh", "hein", "ouais", "hum", "hmm", "ben", "bah", "bon",
    "merci", "voila", "ok", "salut", "bonjour", "yes", "yeah", "allo", "allô"
}


def sans_accents(texte: str) -> str:
    """Retourne la chaîne en minuscules, normalisée sans accents."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", str(texte).lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def est_hallucination(texte: Optional[str]) -> bool:
    """Détecte si la transcription est une hallucination connue de Whisper."""
    if not texte:
        return True
    
    t_clean = texte.strip()
    if len(t_clean) < 2:
        return True

    plat = sans_accents(t_clean)
    
    # Hallucinations textuelles connues
    if any(h in plat for h in HALLUCINATIONS):
        return True

    # Répétitions excessives d'un même mot (ex: "Merci merci merci merci")
    mots = plat.split()
    if len(mots) >= 4 and len(set(mots)) <= 2:
        return True

    # Répétition de caractères de ponctuation
    if re.fullmatch(r"[\s.,!?:;\-_*~]+", t_clean):
        return True

    return False


def nettoyer_transcription(texte: Optional[str]) -> str:
    """Nettoie une transcription brute.
    
    - Détecte et rejette les hallucinations connues (renvoie "").
    - Élimine les résidus de wake-word en tête d'énoncé (ex: "Jarvis, quelle heure est-il" -> "quelle heure est-il").
    - Rejette les résidus orphelins (ex: "Jarvis." seul -> "").
    - Élimine la ponctuation résiduelle en tête.
    """
    if not texte:
        return ""

    if est_hallucination(texte):
        return ""

    t = texte.strip()

    # Cas avec séparateur explicite : "Jarvis, lance Edge", "Avis : quelle heure", "Hey Jarvis - stop"
    for sep in (",", ":", "-", "!", "?", "."):
        if sep in t:
            parties = t.split(sep, 1)
            tete = sans_accents(parties[0].strip().strip("'’\""))
            if tete in RESIDUS_WAKE_WORD:
                t = parties[1].strip()
                break

    # Cas sans ponctuation : "Jarvis lance Edge" ou "hey jarvis quelle heure"
    mots = t.split()
    if mots:
        premier = sans_accents(mots[0].strip("',.:;!?\""))
        if premier in RESIDUS_WAKE_WORD:
            t = " ".join(mots[1:]).strip()
        elif len(mots) >= 2:
            second = sans_accents(mots[1].strip("',.:;!?\""))
            deux_premiers = f"{premier} {second}"
            if deux_premiers in RESIDUS_WAKE_WORD:
                t = " ".join(mots[2:]).strip()

    # Nettoyage ponctuation orpheline en début ou fin
    t = re.sub(r"^[\s,.:;!?-]+", "", t)
    t = re.sub(r"[\s,.:;!?-]+$", "", t)
    t = t.strip()

    # Si ce qui reste est uniquement un résidu de wake-word isolé
    if sans_accents(t) in RESIDUS_WAKE_WORD:
        return ""

    # Si le texte fait moins de 2 caractères ou n'a aucun caractère alphanumérique
    if len(t) < 2 or not any(c.isalnum() for c in t):
        return ""

    # Si c'est un mot parasite isolé sans contexte
    if sans_accents(t) in MOTS_PARASITES_ISOLES:
        return ""

    return t


def est_commande_valide(texte: Optional[str]) -> bool:
    """Vérifie si le texte nettoyé constitue une commande exploitable."""
    nettoye = nettoyer_transcription(texte)
    return len(nettoye) >= 3 and any(c.isalnum() for c in nettoye)
