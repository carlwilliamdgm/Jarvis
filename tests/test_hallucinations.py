"""Tests pour le module jarvis.hallucinations et la protection anti-hallucinations."""

import pytest
from jarvis.hallucinations import (
    sans_accents,
    est_hallucination,
    nettoyer_transcription,
    est_commande_valide,
)


def test_sans_accents():
    assert sans_accents("Bonjour, Ça va ?") == "bonjour, ca va ?"
    assert sans_accents("À bientôt pour une vidéo") == "a bientot pour une video"
    assert sans_accents("") == ""


def test_est_hallucination_phrases_connues():
    hallucinations_whisper = [
        "Sous-titres réalisés par la communauté d'Amara.org",
        "Merci d'avoir regardé cette vidéo.",
        "Merci d'avoir visionné ce contenu",
        "N'oubliez pas de vous abonner !",
        "Abonnez-vous à ma chaîne",
        "À la prochaine vidéo !",
        "Sous-titrage ST' 501",
        "transcription :",
        "Likez et partagez !",
        "[Musique]",
        "(musique)",
        "Thank you for watching!",
        "Please subscribe to the channel",
    ]
    for phrase in hallucinations_whisper:
        assert est_hallucination(phrase), f"Devrait être reconnu comme hallucination: {phrase}"


def test_est_hallucination_bruits_et_vide():
    assert est_hallucination("")
    assert est_hallucination("   ")
    assert est_hallucination("...")
    assert est_hallucination("???")
    assert est_hallucination("a")
    # Répétitions excessives
    assert est_hallucination("merci merci merci merci")
    assert est_hallucination("ah ah ah ah ah")


def test_nettoyer_transcription_residus_wake_word():
    assert nettoyer_transcription("Jarvis, quelle heure est-il ?") == "quelle heure est-il"
    assert nettoyer_transcription("Hey Jarvis : ouvre le navigateur") == "ouvre le navigateur"
    assert nettoyer_transcription("Avis, lance Firefox") == "lance Firefox"
    assert nettoyer_transcription("Dis Jarvis quel temps fait-il") == "quel temps fait-il"
    assert nettoyer_transcription("Jarvis lance VS Code") == "lance VS Code"
    assert nettoyer_transcription("Ok Jarvis ferme la fenêtre") == "ferme la fenêtre"


def test_nettoyer_transcription_rejets():
    # Résidu seul -> doit renvoyer chaîne vide
    assert nettoyer_transcription("Jarvis") == ""
    assert nettoyer_transcription("Jarvis.") == ""
    assert nettoyer_transcription("Hey Jarvis") == ""
    assert nettoyer_transcription("Avis") == ""
    assert nettoyer_transcription("Service") == ""
    # Hallucination -> doit renvoyer chaîne vide
    assert nettoyer_transcription("Merci d'avoir regardé la vidéo.") == ""
    # Mots parasites isolés sans commande
    assert nettoyer_transcription("Ah") == ""
    assert nettoyer_transcription("Hum") == ""
    assert nettoyer_transcription("Merci") == ""


def test_est_commande_valide():
    assert est_commande_valide("Jarvis, allume les lumières")
    assert est_commande_valide("Quelle heure est-il ?")
    assert est_commande_valide("Ouvre le terminal")
    
    assert not est_commande_valide("Jarvis")
    assert not est_commande_valide("Hey Jarvis.")
    assert not est_commande_valide("Merci d'avoir regardé")
    assert not est_commande_valide("...")
    assert not est_commande_valide("")
    assert not est_commande_valide("Ah")


def test_transcrire_flux_rejette_hallucination_groq():
    from unittest.mock import patch, MagicMock
    from jarvis import voice_input

    class StreamWithVAD:
        def __init__(self):
            self.calls = 0
            self.last_speech = True

        def read(self, size):
            import time
            time.sleep(0.08)
            self.calls += 1
            if self.calls <= 3:
                return b"\x01\x00" * size, False
            self.last_speech = False
            return b"\x00\x00" * size, False

    with patch.dict("os.environ", {"JARVIS_USE_GROQ_WHISPER": "1"}), \
         patch("jarvis.voice_transcription.transcrire_audio_groq", return_value="Sous-titres réalisés par Amara.org") as mock_groq:
        result = voice_input.transcrire_flux(StreamWithVAD())
        assert result is None, "Une hallucination Whisper doit être rejetée par transcrire_flux"


def test_transcrire_et_soumettre_ignore_hallucination_ou_residu():
    from unittest.mock import patch
    from jarvis import voice_input

    with patch("jarvis.voice_input.transcrire_flux", return_value="Jarvis."), \
         patch("jarvis.voice_input._soumettre_au_pipeline") as mock_sub:
        res = voice_input.transcrire_et_soumettre(None)
        assert res is None
        mock_sub.assert_not_called()

    with patch("jarvis.voice_input.transcrire_flux", return_value="Merci d'avoir regardé la vidéo"), \
         patch("jarvis.voice_input._soumettre_au_pipeline") as mock_sub:
        res = voice_input.transcrire_et_soumettre(None)
        assert res is None
        mock_sub.assert_not_called()

