"""
Tests pour l'intercepteur de directives (Jalon 1).

Valide que les directives utilisateur sont détectées et persistées de manière
déterministe sans appel LLM.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
import shutil

from context_engine.memory_tools import intercepter_directive
from context_engine.memory import charger_memoire, sauvegarder_memoire, normaliser_memoire
from context_engine.memory_store import reset_memory_stores, get_memory_store
import context_engine.user_profile as user_profile


class TestDirectivesAncrage(unittest.TestCase):
    def setUp(self):
        """Réinitialise le store mémoire avant chaque test."""
        reset_memory_stores()
        self.original_profiles_dir = user_profile.PROFILES_DIR
        self.temp_profiles_dir = Path(tempfile.mkdtemp())
        user_profile.PROFILES_DIR = self.temp_profiles_dir
    
    def tearDown(self):
        """Réinitialise le store mémoire après chaque test."""
        reset_memory_stores()
        user_profile.PROFILES_DIR = self.original_profiles_dir
        shutil.rmtree(self.temp_profiles_dir, ignore_errors=True)
    
    def test_directive_forme_retenue(self):
        """Teste la détection de directives avec forme 'Retiens que...'."""
        message = "Retiens que je préfère les réponses courtes."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, cle, reponse = resultat
        self.assertTrue(est_directive)
        self.assertIn("préfère les réponses courtes", consigne.lower())
        self.assertIsNotNone(cle)
        self.assertIn("Directive ancrée", reponse)
        self.assertIn("Sir", reponse)

    def test_directive_forme_temporelle_avenir(self):
        """Teste la détection de directives avec forme 'À l'avenir...'."""
        message = "À l'avenir, réponds en 2 phrases maximum."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, cle, reponse = resultat
        self.assertTrue(est_directive)
        self.assertIn("réponds en 2 phrases maximum", consigne.lower())
        self.assertIn("Directive ancrée", reponse)

    def test_directive_forme_temporelle_desormais(self):
        """Teste la détection de directives avec forme 'Désormais...'."""
        message = "Désormais, utilise toujours le français."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, cle, reponse = resultat
        self.assertTrue(est_directive)
        self.assertIn("utilise toujours le français", consigne.lower())

    def test_directive_forme_interdiction(self):
        """Teste la détection de directives avec forme 'Ne fais plus...'."""
        message = "Ne fais plus de blagues inutiles."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, cle, reponse = resultat
        self.assertTrue(est_directive)
        # Le pattern capture après "de" donc "blagues inutiles"
        self.assertIn("blagues", consigne.lower())

    def test_directive_forme_exigence(self):
        """Teste la détection de directives avec forme 'Je veux que tu...'."""
        message = "Je veux que tu sois plus concis."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, cle, reponse = resultat
        self.assertTrue(est_directive)
        self.assertIn("sois plus concis", consigne.lower())

    def test_directive_persistance_memoire(self):
        """Teste que la directive est bien persistée dans memory.json."""
        message = "Retiens que j'aime le bleu."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        _, consigne, cle, _ = resultat
        
        profile = user_profile.charger_profil()
        self.assertEqual(profile["directives_personnelles"][cle], consigne)

    def test_directives_are_isolated_per_user(self):
        first = intercepter_directive("Retiens que je préfère le français.", user_id="alice")
        second = intercepter_directive("Retiens que je préfère l'anglais.", user_id="bob")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        alice_profile = user_profile.charger_profil("alice")
        bob_profile = user_profile.charger_profil("bob")
        self.assertIn(first[2], alice_profile["directives_personnelles"])
        self.assertNotIn(first[2], bob_profile["directives_personnelles"])
        self.assertIn(second[2], bob_profile["directives_personnelles"])

    def test_non_directive_question(self):
        """Teste qu'une question n'est pas interceptée comme directive."""
        message = "Est-ce que tu retiens bien ce que je dis ?"
        resultat = intercepter_directive(message)
        
        self.assertIsNone(resultat)

    def test_non_directive_commande_classique(self):
        """Teste qu'une commande classique n'est pas interceptée."""
        message = "lance la musique"
        resultat = intercepter_directive(message)
        
        # Ce test vérifie que les commandes classiques sans marqueurs de directive
        # ne sont pas interceptées (pattern plus strict pour éviter faux positifs)
        self.assertIsNone(resultat)

    def test_non_directive_simple_acknowledgment(self):
        """Teste qu'un simple acquittement n'est pas intercepté."""
        message = "ok merci"
        resultat = intercepter_directive(message)
        
        self.assertIsNone(resultat)

    def test_directive_casse_et_accents(self):
        """Teste la gestion de la casse et des accents."""
        # Test avec différentes casses
        message1 = "A L'AVENIR, sois plus rapide."
        resultat1 = intercepter_directive(message1)
        self.assertIsNotNone(resultat1)
        
        # Test avec accents normaux
        message2 = "Désormais, utilise l'anglais."
        resultat2 = intercepter_directive(message2)
        self.assertIsNotNone(resultat2)
        
        # Test sans accents (faute de frappe)
        message3 = "Desormais, utilise l'anglais."
        resultat3 = intercepter_directive(message3)
        self.assertIsNotNone(resultat3)

    def test_directive_ponctuation_finale(self):
        """Teste que la ponctuation finale est nettoyée."""
        message = "Retiens que je préfère le silence!!!"
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        _, consigne, _, _ = resultat
        self.assertFalse(consigne.endswith("!"))
        self.assertIn("silence", consigne.lower())

    def test_directive_multiple_appels(self):
        """Teste que plusieurs directives génèrent des clés uniques."""
        messages = [
            "Retiens que j'aime le bleu.",
            "À l'avenir, sois rapide.",
            "Désormais, utilise le français.",
        ]
        
        cles = []
        for msg in messages:
            resultat = intercepter_directive(msg)
            self.assertIsNotNone(resultat)
            _, _, cle, _ = resultat
            cles.append(cle)
        
        # Vérifier que les clés sont uniques (grâce au timestamp)
        self.assertEqual(len(set(cles)), len(cles))
        
        # Vérifier que toutes les directives restent dans le profil actif.
        profile = user_profile.charger_profil()
        for cle in cles:
            self.assertIn(cle, profile["directives_personnelles"])

    def test_directive_message_vide(self):
        """Teste qu'un message vide n'est pas intercepté."""
        message = ""
        resultat = intercepter_directive(message)
        
        self.assertIsNone(resultat)

    def test_directive_message_espaces_seuls(self):
        """Teste qu'un message avec seulement des espaces n'est pas intercepté."""
        message = "   "
        resultat = intercepter_directive(message)
        
        self.assertIsNone(resultat)

    def test_directive_consigne_trop_courte(self):
        """Teste qu'une consigne trop courte est ignorée."""
        message = "Retiens que a."
        resultat = intercepter_directive(message)
        
        # La consigne extraite serait "a" (1 caractère), donc ignorée
        # selon la règle len(consigne) < 3
        self.assertIsNone(resultat)

    def test_directive_ton_jarvis_reponse(self):
        """Teste que la réponse Jarvis a le ton approprié."""
        message = "Retiens que je suis ton maître."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        _, _, _, reponse = resultat
        self.assertIn("Directive ancrée", reponse)
        self.assertIn("Sir", reponse)
        self.assertIn("Je retiens", reponse)

    def test_directive_avec_amorce_jarvis(self):
        """Teste qu'une directive précédée du nom de Jarvis est bien interceptée."""
        message = "Jarvis, retiens que je préfère le thème sombre."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, _, reponse = resultat
        self.assertTrue(est_directive)
        self.assertIn("préfère le thème sombre", consigne.lower())

    def test_directive_avec_amorce_politesse(self):
        """Teste qu'une directive avec formule de politesse est interceptée."""
        message = "S'il te plaît, désormais réponds en 3 lignes maximum."
        resultat = intercepter_directive(message)
        
        self.assertIsNotNone(resultat)
        est_directive, consigne, _, _ = resultat
        self.assertTrue(est_directive)
        self.assertIn("réponds en 3 lignes", consigne.lower())

    def test_directive_interdiction_elargie(self):
        """Teste les verbes d'interdiction enrichis (génère, utilise, etc.)."""
        message1 = "Ne génère plus de listes d'URLs brutes."
        res1 = intercepter_directive(message1)
        self.assertIsNotNone(res1)
        self.assertIn("listes d'urls brutes", res1[1].lower())

        message2 = "N'utilise plus ce ton impersonnel."
        res2 = intercepter_directive(message2)
        self.assertIsNotNone(res2)
        self.assertIn("ton impersonnel", res2[1].lower())

    def test_question_avec_amorce_non_interceptee(self):
        """Teste qu'une question précédée de 'Jarvis' n'est pas faussement interceptée."""
        message = "Jarvis, comment vas-tu aujourd'hui ?"
        res = intercepter_directive(message)
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
