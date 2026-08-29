"""
Tests pour le module de recherche web avancée.
"""

import unittest
try:
    import pytest
except ImportError:
    class _MarkStub:
        def __getattr__(self, name):
            return lambda *a, **kw: (lambda f: f)
    class _PytestStub:
        mark = _MarkStub()
        @staticmethod
        def skip(reason=""):
            raise unittest.SkipTest(reason)
    pytest = _PytestStub()  # type: ignore[assignment]
from capabilities.web_search import (
    WebSearchEngine,
    rechercher_web,
    analyser_page_web,
    rechercher_et_analyser,
    extraire_informations_cles,
    synthetiser_resultats
)


class TestWebSearchEngine(unittest.TestCase):
    """Tests pour la classe WebSearchEngine."""
    
    def test_init(self):
        """Test l'initialisation du moteur de recherche."""
        engine = WebSearchEngine()
        self.assertIsNotNone(engine.session)
        self.assertEqual(engine.min_request_interval, 1.0)
    
    def test_rate_limit(self):
        """Test la limitation de taux."""
        engine = WebSearchEngine()
        import time
        
        # Premier appel
        start = time.time()
        engine._rate_limit()
        first_duration = time.time() - start
        
        # Deuxième appel immédiat
        start = time.time()
        engine._rate_limit()
        second_duration = time.time() - start
        
        # Le deuxième appel devrait prendre plus de temps à cause du rate limiting
        self.assertGreaterEqual(second_duration, 0.9)  # Allow small margin
    
    def test_search_duckduckgo(self):
        """Test la recherche DuckDuckGo."""
        engine = WebSearchEngine()
        results = engine.search_duckduckgo("Python programming", num_results=3)
        
        self.assertIsInstance(results, list)
        # Les résultats peuvent être vides en cas d'erreur réseau
        if results and "error" not in results[0]:
            self.assertLessEqual(len(results), 3)
            self.assertIn("title", results[0])
            self.assertIn("url", results[0])
    
    def test_clean_duckduckgo_url(self):
        """Test le nettoyage des URLs DuckDuckGo."""
        engine = WebSearchEngine()
        
        # URL avec redirect
        redirect_url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&test=param"
        clean_url = engine._clean_duckduckgo_url(redirect_url)
        self.assertIn("example.com", clean_url)
        
        # URL normale
        normal_url = "https://example.com"
        self.assertEqual(engine._clean_duckduckgo_url(normal_url), normal_url)
    
    def test_fetch_page_content(self):
        """Test la récupération de contenu de page."""
        engine = WebSearchEngine()
        
        # Test avec une page réelle (peut échouer si pas de connexion internet)
        result = engine.fetch_page_content("https://example.com", max_length=1000)
        
        self.assertIsInstance(result, dict)
        self.assertIn("url", result)
        self.assertIn("status", result)
        
        if result["status"] == "success":
            self.assertIn("title", result)
            self.assertIn("content", result)
            self.assertIn("length", result)


class TestWebSearchFunctions(unittest.TestCase):
    """Tests pour les fonctions de recherche web."""
    
    def test_rechercher_web(self):
        """Test la fonction de recherche web."""
        result = rechercher_web("Python programming", nombre_resultats=3)
        
        self.assertIsInstance(result, str)
        self.assertTrue("RÉSULTATS DE RECHERCHE" in result or "Erreur" in result)
    
    def test_analyser_page_web(self):
        """Test l'analyse de page web."""
        result = analyser_page_web("https://example.com")
        
        self.assertIsInstance(result, str)
        self.assertTrue("ANALYSE DE LA PAGE" in result or "Erreur" in result)
    
    def test_rechercher_et_analyser(self):
        """Test la recherche combinée avec analyse."""
        result = rechercher_et_analyser("Python", nombre_pages=1)
        
        self.assertIsInstance(result, str)
        self.assertTrue("RÉSULTATS DE RECHERCHE" in result or "Erreur" in result)
    
    def test_extraire_informations_cles(self):
        """Test l'extraction d'informations clés."""
        texte = """
        Contactez-nous à contact@example.com ou support@test.com.
        Visitez https://example.com ou https://test.org.
        Le prix est 50€ et la réduction est 20%.
        La date limite est 15/03/2024.
        """
        
        result = extraire_informations_cles(texte)
        
        self.assertIsInstance(result, str)
        self.assertIn("INFORMATIONS CLÉS", result)
        # Vérifier que des informations ont été extraites
        self.assertTrue(
            "Emails" in result or "URLs" in result or "Nombres" in result or "Dates" in result
        )
    
    def test_extraire_informations_cles_vide(self):
        """Test l'extraction sur un texte vide."""
        result = extraire_informations_cles("Texte sans informations particulières.")
        
        self.assertIsInstance(result, str)
        self.assertIn("INFORMATIONS CLÉS", result)
        self.assertIn("Aucune information clé détectée", result)
    
    def test_synthetiser_resultats(self):
        """Test la synthèse de résultats."""
        resultats = [
            "Résultat 1 avec des informations importantes.",
            "Résultat 2 contenant des données supplémentaires.",
            "Résultat 3 avec des détails techniques."
        ]
        
        result = synthetiser_resultats(resultats)
        
        self.assertIsInstance(result, str)
        self.assertIn("SYNTHÈSE DES RÉSULTATS", result)
        self.assertTrue("3 sources" in result or "sources analysées: 3" in result or "3" in result)
    
    def test_synthetiser_resultats_vide(self):
        """Test la synthèse avec une liste vide."""
        result = synthetiser_resultats([])
        
        self.assertIsInstance(result, str)
        self.assertIn("Aucun résultat à synthétiser", result)


class TestWebSearchIntegration(unittest.TestCase):
    """Tests d'intégration pour la recherche web."""
    
    def test_recherche_complete_workflow(self):
        """Test un workflow complet de recherche et analyse."""
        # Rechercher
        resultat_recherche = rechercher_web("Python", nombre_resultats=2)
        self.assertIsInstance(resultat_recherche, str)
        
        # Si la recherche a réussi, essayer d'analyser une page
        if "Erreur" not in resultat_recherche and "example.com" in resultat_recherche:
            resultat_analyse = analyser_page_web("https://example.com")
            self.assertIsInstance(resultat_analyse, str)
    
    def test_extraction_chain(self):
        """Test une chaîne d'extraction et synthèse."""
        texte = """
        Pour plus d'informations, contactez admin@company.com.
        Visitez notre site https://company.com/products.
        Le coût total est 1000€ avec une remise de 15%.
        """
        
        # Extraire les informations
        infos = extraire_informations_cles(texte)
        self.assertIn("INFORMATIONS CLÉS", infos)
        
        # Synthétiser
        synthese = synthetiser_resultats([texte, texte])
        self.assertIn("SYNTHÈSE DES RÉSULTATS", synthese)


@pytest.mark.slow
class TestWebSearchSlow(unittest.TestCase):
    """Tests lents nécessitant une connexion internet stable."""
    
    def test_recherche_temps_reel(self):
        """Test une recherche en temps réel avec internet."""
        result = rechercher_web("actualités technologie", nombre_resultats=5)
        
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)
    
    def test_analyse_page_complexe(self):
        """Test l'analyse d'une page web complexe."""
        result = analyser_page_web("https://example.com")
        
        self.assertIsInstance(result, str)
        if "Erreur" not in result:
            self.assertIn("Titre", result)
            self.assertIn("CONTENU", result)
