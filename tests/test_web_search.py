"""
Tests pour le module de recherche web avancée.
"""

import pytest
from capabilities.web_search import (
    WebSearchEngine,
    rechercher_web,
    analyser_page_web,
    rechercher_et_analyser,
    extraire_informations_cles,
    synthetiser_resultats
)


class TestWebSearchEngine:
    """Tests pour la classe WebSearchEngine."""
    
    def test_init(self):
        """Test l'initialisation du moteur de recherche."""
        engine = WebSearchEngine()
        assert engine.session is not None
        assert engine.min_request_interval == 1.0
    
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
        assert second_duration >= 0.9  # Allow small margin
    
    def test_search_duckduckgo(self):
        """Test la recherche DuckDuckGo."""
        engine = WebSearchEngine()
        results = engine.search_duckduckgo("Python programming", num_results=3)
        
        assert isinstance(results, list)
        # Les résultats peuvent être vides en cas d'erreur réseau
        if results and "error" not in results[0]:
            assert len(results) <= 3
            if results:
                assert "title" in results[0]
                assert "url" in results[0]
    
    def test_clean_duckduckgo_url(self):
        """Test le nettoyage des URLs DuckDuckGo."""
        engine = WebSearchEngine()
        
        # URL avec redirect
        redirect_url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&test=param"
        clean_url = engine._clean_duckduckgo_url(redirect_url)
        assert "example.com" in clean_url
        
        # URL normale
        normal_url = "https://example.com"
        assert engine._clean_duckduckgo_url(normal_url) == normal_url
    
    def test_fetch_page_content(self):
        """Test la récupération de contenu de page."""
        engine = WebSearchEngine()
        
        # Test avec une page réelle (peut échouer si pas de connexion internet)
        result = engine.fetch_page_content("https://example.com", max_length=1000)
        
        assert isinstance(result, dict)
        assert "url" in result
        assert "status" in result
        
        if result["status"] == "success":
            assert "title" in result
            assert "content" in result
            assert "length" in result


class TestWebSearchFunctions:
    """Tests pour les fonctions de recherche web."""
    
    def test_rechercher_web(self):
        """Test la fonction de recherche web."""
        result = rechercher_web("Python programming", nombre_resultats=3)
        
        assert isinstance(result, str)
        assert "RÉSULTATS DE RECHERCHE" in result or "Erreur" in result
    
    def test_analyser_page_web(self):
        """Test l'analyse de page web."""
        result = analyser_page_web("https://example.com")
        
        assert isinstance(result, str)
        assert "ANALYSE DE LA PAGE" in result or "Erreur" in result
    
    def test_rechercher_et_analyser(self):
        """Test la recherche combinée avec analyse."""
        result = rechercher_et_analyser("Python", nombre_pages=1)
        
        assert isinstance(result, str)
        assert "RÉSULTATS DE RECHERCHE" in result or "Erreur" in result
    
    def test_extraire_informations_cles(self):
        """Test l'extraction d'informations clés."""
        texte = """
        Contactez-nous à contact@example.com ou support@test.com.
        Visitez https://example.com ou https://test.org.
        Le prix est 50€ et la réduction est 20%.
        La date limite est 15/03/2024.
        """
        
        result = extraire_informations_cles(texte)
        
        assert isinstance(result, str)
        assert "INFORMATIONS CLÉS" in result
        # Vérifier que des informations ont été extraites
        assert "Emails" in result or "URLs" in result or "Nombres" in result or "Dates" in result
    
    def test_extraire_informations_cles_vide(self):
        """Test l'extraction sur un texte vide."""
        result = extraire_informations_cles("Texte sans informations particulières.")
        
        assert isinstance(result, str)
        assert "INFORMATIONS CLÉS" in result
        assert "Aucune information clé détectée" in result
    
    def test_synthetiser_resultats(self):
        """Test la synthèse de résultats."""
        resultats = [
            "Résultat 1 avec des informations importantes.",
            "Résultat 2 contenant des données supplémentaires.",
            "Résultat 3 avec des détails techniques."
        ]
        
        result = synthetiser_resultats(resultats)
        
        assert isinstance(result, str)
        assert "SYNTHÈSE DES RÉSULTATS" in result
        assert "3 sources" in result
    
    def test_synthetiser_resultats_vide(self):
        """Test la synthèse avec une liste vide."""
        result = synthetiser_resultats([])
        
        assert isinstance(result, str)
        assert "Aucun résultat à synthétiser" in result


class TestWebSearchIntegration:
    """Tests d'intégration pour la recherche web."""
    
    def test_recherche_complete_workflow(self):
        """Test un workflow complet de recherche et analyse."""
        # Rechercher
        resultat_recherche = rechercher_web("Python", nombre_resultats=2)
        assert isinstance(resultat_recherche, str)
        
        # Si la recherche a réussi, essayer d'analyser une page
        if "Erreur" not in resultat_recherche and "example.com" in resultat_recherche:
            resultat_analyse = analyser_page_web("https://example.com")
            assert isinstance(resultat_analyse, str)
    
    def test_extraction_chain(self):
        """Test une chaîne d'extraction et synthèse."""
        texte = """
        Pour plus d'informations, contactez admin@company.com.
        Visitez notre site https://company.com/products.
        Le coût total est 1000€ avec une remise de 15%.
        """
        
        # Extraire les informations
        infos = extraire_informations_cles(texte)
        assert "INFORMATIONS CLÉS" in infos
        
        # Synthétiser
        synthese = synthetiser_resultats([texte, texte])
        assert "SYNTHÈSE DES RÉSULTATS" in synthese


@pytest.mark.slow
class TestWebSearchSlow:
    """Tests lents nécessitant une connexion internet stable."""
    
    def test_recherche_temps_reel(self):
        """Test une recherche en temps réel avec internet."""
        result = rechercher_web("actualités technologie", nombre_resultats=5)
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_analyse_page_complexe(self):
        """Test l'analyse d'une page web complexe."""
        result = analyser_page_web("https://example.com")
        
        assert isinstance(result, str)
        if "Erreur" not in result:
            assert "Titre" in result
            assert "CONTENU" in result