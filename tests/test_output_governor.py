"""
Tests pour le Gouverneur de Sortie (Output Governor / Anti-Dump) - Jalon 3.

Valide que :
- Les dumps d'URLs brutes sont nettoyés selon le profil utilisateur
- Les scories techniques sont épurées
- Le format de réponse respecte les préférences du profil
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from context_engine.output_governor import (
    gouverner_sortie,
    _detecter_dump_urls,
    _nettoyer_dump_urls,
    _epurer_scories_techniques,
    _appliquer_concision,
)


class TestOutputGovernor(unittest.TestCase):
    def setUp(self):
        """Initialise l'environnement de test."""
        # Créer un répertoire temporaire pour les profils
        self.temp_dir = tempfile.mkdtemp()
        self.profiles_dir = Path(self.temp_dir) / "learning" / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
    
    def tearDown(self):
        """Nettoie l'environnement de test."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_texte_normal_passe_intact(self):
        """Teste qu'un texte normal sans scories passe sans modification inutile."""
        texte = "Voici une réponse normale et propre pour l'utilisateur."
        resultat = gouverner_sortie(texte, user_id=None)
        
        # Sans profil configuré, le texte devrait rester intact
        self.assertEqual(resultat, texte)
    
    def test_detection_dump_urls(self):
        """Teste la détection de dumps d'URLs brutes."""
        # Cas avec dump (plus de 2 URLs longues)
        texte_dump = "Voici les résultats :\nhttps://example.com/very-long-url-1\nhttps://example.com/very-long-url-2\nhttps://example.com/very-long-url-3"
        self.assertTrue(_detecter_dump_urls(texte_dump))
        
        # Cas sans dump (moins de 3 URLs)
        texte_sain = "Voici un lien : https://example.com/short et un autre : https://example.org/another"
        self.assertFalse(_detecter_dump_urls(texte_sain))
        
        # Cas sans URL
        texte_sans_url = "Voici du texte sans aucun lien."
        self.assertFalse(_detecter_dump_urls(texte_sans_url))
    
    def test_nettoyage_dump_urls_mode_synthese(self):
        """Teste qu'un dump d'URLs est assaini en mode synthèse."""
        texte_dump = "Voici les résultats :\nhttps://example.com/very-long-url-1\nhttps://example.com/very-long-url-2\nhttps://example.com/very-long-url-3\nhttps://example.com/very-long-url-4\nhttps://example.com/very-long-url-5"
        
        resultat = _nettoyer_dump_urls(texte_dump, mode_synthese=True)
        
        # En mode synthèse, les URLs brutes devraient être supprimées
        self.assertNotIn("https://example.com/very-long-url-1", resultat)
        self.assertNotIn("https://example.com/very-long-url-2", resultat)
        self.assertNotIn("https://example.com/very-long-url-3", resultat)
        self.assertNotIn("https://example.com/very-long-url-4", resultat)
        self.assertNotIn("https://example.com/very-long-url-5", resultat)
        # Le texte contextuel devrait rester
        self.assertIn("Voici les résultats", resultat)
    
    def test_nettoyage_dump_urls_mode_detaille(self):
        """Teste qu'en mode détaillé, les URLs sont conservées mais nettoyées."""
        texte_dump = "Voici les résultats :\nhttps://example.com/very-long-url-1\nhttps://example.com/very-long-url-2\nhttps://example.com/very-long-url-3"
        
        resultat = _nettoyer_dump_urls(texte_dump, mode_synthese=False)
        
        # En mode détaillé, les URLs devraient être conservées
        self.assertIn("https://example.com/very-long-url-1", resultat)
        self.assertIn("https://example.com/very-long-url-2", resultat)
        self.assertIn("https://example.com/very-long-url-3", resultat)
    
    def test_epuration_scories_techniques(self):
        """Teste que les scories techniques sont épurées."""
        texte_avec_scories = """Voici le résultat de l'action.
CapabilityResult status=SUCCESS
0x80070005
Exception: Division by zero
Traceback (most recent call last):
  File "test.py", line 42
L'action a réussi malgré tout."""
        
        resultat = _epurer_scories_techniques(texte_avec_scories)
        
        # Les scories devraient être éliminées
        self.assertNotIn("CapabilityResult status=", resultat)
        self.assertNotIn("0x80070005", resultat)
        self.assertNotIn("Exception: Division by zero", resultat)
        self.assertNotIn("Traceback (most recent call last):", resultat)
        self.assertNotIn('File "test.py", line 42', resultat)
        
        # Le texte utile devrait rester
        self.assertIn("Voici le résultat de l'action", resultat)
        self.assertIn("L'action a réussi malgré tout", resultat)
    
    def test_epuration_codes_erreur_hexadecimaux(self):
        """Teste l'épuration des codes d'erreur hexadécimaux."""
        # Test avec une ligne dédiée au code d'erreur (ligne supprimée)
        texte = "Erreur critique.\n0x80070005\nL'action a échoué."
        resultat = _epurer_scories_techniques(texte)
        
        self.assertNotIn("0x80070005", resultat)
        self.assertIn("Erreur critique", resultat)
        self.assertIn("L'action a échoué", resultat)
    
    def test_epuration_stack_traces(self):
        """Teste l'épuration des stack traces."""
        texte = """Erreur survenue.
Traceback (most recent call last):
  File "main.py", line 123, in <module>
    execute()
  File "utils.py", line 45, in execute
    process_data()
ValueError: Invalid input
Fin du rapport."""
        
        resultat = _epurer_scories_techniques(texte)
        
        self.assertNotIn("Traceback (most recent call last):", resultat)
        self.assertNotIn('File "main.py", line 123', resultat)
        self.assertNotIn('File "utils.py", line 45', resultat)
        self.assertIn("Erreur survenue", resultat)
        self.assertIn("Fin du rapport", resultat)
    
    def test_application_concision(self):
        """Teste l'application de la concision."""
        texte_avec_repetitions = """Voici le résultat.
Voici le résultat.
L'action est terminée.
L'action est terminée."""
        
        resultat = _appliquer_concision(texte_avec_repetitions, concis=True)
        
        # Les répétitions devraient être éliminées
        self.assertEqual(resultat.count("Voici le résultat"), 1)
        self.assertEqual(resultat.count("L'action est terminée"), 1)
    
    def test_application_concision_desactivee(self):
        """Teste que la concision désactivée conserve les répétitions."""
        texte_avec_repetitions = """Voici le résultat.
Voici le résultat.
L'action est terminée."""
        
        resultat = _appliquer_concision(texte_avec_repetitions, concis=False)
        
        # Les répétitions devraient être conservées
        self.assertEqual(resultat.count("Voici le résultat"), 2)
    
    def test_suppression_lignes_vides_multiples(self):
        """Teste que les lignes vides multiples sont réduites."""
        texte_avec_vide = """Première ligne.


Deuxième ligne.



Troisième ligne."""
        
        resultat = _appliquer_concision(texte_avec_vide, concis=True)
        
        # Les lignes vides multiples devraient être réduites à un seul saut
        self.assertNotIn("\n\n\n", resultat)
    
    def test_gouverner_sortie_avec_profil_synthese(self):
        """Teste le gouverneur avec un profil en mode synthèse."""
        texte_avec_dump = """Voici les résultats de recherche.
https://example.com/very-long-url-1
https://example.com/very-long-url-2
https://example.com/very-long-url-3
J'ai trouvé 3 sources pertinentes."""
        
        # Mock du profil utilisateur en mode synthèse
        mock_profil = {
            "user_id": "test_user",
            "style_cognitif": {
                "format_prefere": "synthese",
                "concis": True,
            }
        }
        
        with patch('context_engine.user_profile.charger_profil', return_value=mock_profil):
            resultat = gouverner_sortie(texte_avec_dump, user_id="test_user")
        
        # Les URLs brutes devraient être supprimées en mode synthèse
        self.assertNotIn("https://example.com/very-long-url-1", resultat)
        self.assertNotIn("https://example.com/very-long-url-2", resultat)
        self.assertNotIn("https://example.com/very-long-url-3", resultat)
        self.assertIn("Voici les résultats de recherche", resultat)
    
    def test_gouverner_sortie_avec_profil_detaille(self):
        """Teste le gouverneur avec un profil en mode détaillé."""
        texte_avec_dump = """Voici les résultats de recherche.
https://example.com/very-long-url-1
https://example.com/very-long-url-2
https://example.com/very-long-url-3
J'ai trouvé 3 sources pertinentes."""
        
        # Mock du profil utilisateur en mode détaillé
        mock_profil = {
            "user_id": "test_user",
            "style_cognitif": {
                "format_prefere": "detaille",
                "concis": False,
            }
        }
        
        with patch('context_engine.user_profile.charger_profil', return_value=mock_profil):
            resultat = gouverner_sortie(texte_avec_dump, user_id="test_user")
        
        # En mode détaillé, les URLs devraient être conservées
        self.assertIn("https://example.com/very-long-url-1", resultat)
        self.assertIn("https://example.com/very-long-url-2", resultat)
        self.assertIn("https://example.com/very-long-url-3", resultat)
    
    def test_gouverner_sortie_avec_scories_et_profil(self):
        """Teste le gouverneur avec scories techniques et profil."""
        texte_avec_scories = """Résultat de l'action.
CapabilityResult status=SUCCESS
0x12345678
L'action a réussi."""
        
        # Mock du profil utilisateur
        mock_profil = {
            "user_id": "test_user",
            "style_cognitif": {
                "format_prefere": "synthese",
                "concis": True,
            }
        }
        
        with patch('context_engine.user_profile.charger_profil', return_value=mock_profil):
            resultat = gouverner_sortie(texte_avec_scories, user_id="test_user")
        
        # Les scories devraient être épurées
        self.assertNotIn("CapabilityResult status=", resultat)
        self.assertNotIn("0x12345678", resultat)
        self.assertIn("Résultat de l'action", resultat)
        self.assertIn("L'action a réussi", resultat)
    
    def test_gouverner_sortie_texte_vide(self):
        """Teste qu'un texte vide reste vide."""
        resultat = gouverner_sortie("", user_id=None)
        self.assertEqual(resultat, "")
    
    def test_gouverner_sortie_texte_espaces(self):
        """Teste qu'un texte avec seulement des espaces est conservé."""
        texte = "   "
        resultat = gouverner_sortie(texte, user_id=None)
        self.assertEqual(resultat, texte)
    
    def test_gouverner_sortie_erreur_chargement_profil(self):
        """Teste que le gouverneur fonctionne même si le profil ne charge pas."""
        texte = "Voici une réponse normale."
        
        with patch('context_engine.user_profile.charger_profil', side_effect=Exception("Erreur de chargement")):
            resultat = gouverner_sortie(texte, user_id="test_user")
        
        # Avec les valeurs par défaut (mode_synthese=True, concis=True), le texte devrait rester intact
        self.assertEqual(resultat, texte)
    
    def test_gouverner_sortie_scenario_complet(self):
        """Teste un scénario complet avec dump, scories et répétitions."""
        texte_complexe = """Voici les résultats de recherche.
https://example.com/very-long-url-1
https://example.com/very-long-url-2
https://example.com/very-long-url-3
https://example.com/very-long-url-4
https://example.com/very-long-url-5

CapabilityResult status=SUCCESS
0xDEADBEEF

Voici les résultats de recherche.
J'ai trouvé 5 sources."""
        
        # Mock du profil utilisateur en mode synthèse et concis
        mock_profil = {
            "user_id": "test_user",
            "style_cognitif": {
                "format_prefere": "synthese",
                "concis": True,
            }
        }
        
        with patch('context_engine.user_profile.charger_profil', return_value=mock_profil):
            resultat = gouverner_sortie(texte_complexe, user_id="test_user")
        
        # Vérifications
        self.assertNotIn("https://example.com/very-long-url-1", resultat)
        self.assertNotIn("CapabilityResult status=", resultat)
        self.assertNotIn("0xDEADBEEF", resultat)
        # La concision supprime les répétitions consécutives, mais pas les répétitions
        # séparées par d'autres lignes (comportement actuel)
        self.assertIn("Voici les résultats de recherche", resultat)
        self.assertIn("J'ai trouvé 5 sources", resultat)


if __name__ == "__main__":
    unittest.main()
