"""Pré-filtre wake-word local ultra-rapide pour le démon temps réel.

Architecture :
  Énergie audio → Vosk (CPU, <50 ms) → mot-clé détecté ? → Groq Whisper
                                        NON → ignorer silencieusement

Avantages :
  - Zéro appel API sur la TV, la radio ou les bruits ambiants.
  - Zéro freeze : Vosk tourne en RAM, aucune latence réseau.
  - Réutilise le modèle déjà chargé par voice_input.py (singleton).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Sequence

LOGGER = logging.getLogger(__name__)

# ── Mots-clés déclencheurs reconnus par le pré-filtre local ──────────────────
_MOTS_JARVIS: tuple[str, ...] = (
    "jarvis", "jervis", "jarvi", "jarbie", "jarbi",
    "jarwis", "jarves", "jarvice",
    # Variantes phonétiques / homophones fréquents
    "service", "servis", "j'envisse", "envisse", "djarvis",
    # Commandes directes sans mot-clé qui doivent passer
    "regarde", "analyse",
)

# Durée minimale d'audio (en octets PCM 16-bit 16kHz) pour valoir la peine d'être analysée.
# 0.3 s × 16000 samples/s × 2 bytes/sample = 9600 bytes
_MIN_PCM_BYTES = 9_600


def _charger_modele_vosk():
    """Retourne le modèle Vosk déjà chargé (singleton partagé avec voice_input)."""
    try:
        from jarvis.voice_input import get_vosk_model
        return get_vosk_model()
    except Exception as exc:
        LOGGER.warning("[WakeWordLocal] Impossible de charger le modèle Vosk : %s", exc)
        return None


def contient_mot_cle(texte: str, mots_cles: Sequence[str] = _MOTS_JARVIS) -> bool:
    """Retourne True si le texte contient l'un des mots-clés."""
    t = texte.lower()
    return any(m in t for m in mots_cles)


def detecter_wakeword_local(pcm_data: bytes, sample_rate: int = 16_000) -> bool:
    """Analyse un chunk PCM avec Vosk et retourne True si un mot-clé est détecté.

    Cette fonction est intentionnellement rapide (<50 ms) et ne fait aucun appel
    réseau. Elle est conçue pour être appelée avant ``transcrire_audio_groq``.

    Args:
        pcm_data: Données PCM brutes 16-bit little-endian mono.
        sample_rate: Fréquence d'échantillonnage (doit correspondre au modèle Vosk).

    Returns:
        True si un mot-clé déclencheur a été détecté, False sinon.
    """
    if len(pcm_data) < _MIN_PCM_BYTES:
        return False  # Chunk trop court pour être de la parole

    modele = _charger_modele_vosk()
    if modele is None:
        # Vosk indisponible → laisser passer pour ne pas bloquer Jarvis
        LOGGER.debug("[WakeWordLocal] Vosk absent → passe-tout activé.")
        return True

    try:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(modele, sample_rate)
        rec.SetWords(False)

        # Envoyer le chunk audio
        rec.AcceptWaveform(pcm_data)

        # Lire le résultat partiel et final
        partiel = json.loads(rec.PartialResult()).get("partial", "")
        final   = json.loads(rec.FinalResult()).get("text", "")

        texte_complet = f"{partiel} {final}".strip()
        LOGGER.debug("[WakeWordLocal] Vosk → %r", texte_complet)

        if texte_complet and contient_mot_cle(texte_complet):
            LOGGER.info("[WakeWordLocal] ✅ Mot-clé détecté localement : %r", texte_complet)
            return True

        if texte_complet:
            LOGGER.debug("[WakeWordLocal] ❌ Ignoré (pas de mot-clé) : %r", texte_complet)
        return False

    except Exception as exc:
        LOGGER.warning("[WakeWordLocal] Erreur Vosk : %s → passe-tout.", exc)
        return True  # Fail-open : en cas d'erreur, ne pas bloquer
