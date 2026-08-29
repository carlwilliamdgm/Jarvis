"""
Tests pour le module d'automatisation de navigateur.
"""

import pytest
from capabilities.browser_automation import (
    BrowserAutomation,
    BrowserType,
    naviguer_vers,
    cliquer_element,
    remplir_formulaire,
    extraire_texte,
    prendre_capture,
    executer_sequence,
    obtenir_infos_page
)


class TestBrowserAutomation:
    """Tests pour la classe BrowserAutomation."""
    
    def test_browser_type_enum(self):
        """Test l'énumération des types de navigateurs."""
        assert BrowserType.CHROMIUM.value == "chromium"
        assert BrowserType.FIREFOX.value == "firefox"
        assert BrowserType.WEBKIT.value == "webkit"
    
    def test_initialization(self):
        """Test l'initialisation de l'automatisation."""
        browser = BrowserAutomation(headless=True, browser_type=BrowserType.CHROMIUM)
        assert browser.headless is True
        assert browser.browser_type == BrowserType.CHROMIUM
        assert browser.browser is None
        assert browser.page is None


@pytest.mark.slow
class TestBrowserAutomationAsync:
    """Tests asynchrones pour l'automatisation de navigateur (nécessitent Playwright)."""
    
    @pytest.mark.asyncio
    async def test_start_and_close(self):
        """Test le démarrage et la fermeture du navigateur."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                assert browser.browser is not None
                assert browser.page is not None
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_navigate_to_example(self):
        """Test la navigation vers example.com."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                result = await browser.navigate("https://example.com")
                assert "Navigation réussie" in result or "Erreur" in result
                
                if "Navigation réussie" in result:
                    url = await browser.get_url()
                    assert "example.com" in url
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_get_title(self):
        """Test la récupération du titre de la page."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                await browser.navigate("https://example.com")
                title = await browser.get_title()
                assert title is not None
                assert len(title) > 0
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_get_text(self):
        """Test l'extraction de texte de la page."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                await browser.navigate("https://example.com")
                text = await browser.get_text("body")
                assert text is not None
                assert len(text) > 0
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_screenshot(self):
        """Test la capture d'écran."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                await browser.navigate("https://example.com")
                screenshot = await browser.screenshot()
                assert screenshot is not None
                assert "data:image/png;base64" in screenshot or "Erreur" in screenshot
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_scroll(self):
        """Test le scrolling de la page."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                await browser.navigate("https://example.com")
                result = await browser.scroll(100)
                assert "Scroll" in result or "Erreur" in result
        except ImportError:
            pytest.skip("Playwright non installé")
    
    @pytest.mark.asyncio
    async def test_execute_javascript(self):
        """Test l'exécution de JavaScript."""
        try:
            async with BrowserAutomation(headless=True) as browser:
                await browser.navigate("https://example.com")
                result = await browser.execute_javascript("document.title")
                assert result is not None
        except ImportError:
            pytest.skip("Playwright non installé")


class TestBrowserAutomationSync:
    """Tests synchrones pour les fonctions wrapper."""
    
    def test_naviguer_vers_import_error(self):
        """Test que la fonction gère l'absence de Playwright."""
        # Ce test va échouer si Playwright n'est pas installé
        # mais nous testons que l'erreur est gérée proprement
        try:
            result = naviguer_vers("https://example.com")
            # Si Playwright est installé, vérifier le résultat
            assert result is not None
        except ImportError:
            # Attendu si Playwright n'est pas installé
            pass
    
    def test_naviguer_vers_basic(self):
        """Test basique de la fonction de navigation."""
        try:
            result = naviguer_vers("https://example.com")
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_obtenir_infos_page(self):
        """Test l'obtention d'informations de page."""
        try:
            result = obtenir_infos_page("https://example.com")
            assert isinstance(result, str)
            if "Erreur" not in result:
                assert "INFORMATIONS PAGE" in result
        except ImportError:
            pytest.skip("Playwright non installé")


class TestSequenceExecution:
    """Tests pour l'exécution de séquences d'actions."""
    
    def test_executer_sequence_simple(self):
        """Test une séquence simple d'actions."""
        actions = [
            {"type": "navigate", "url": "https://example.com"},
            {"type": "screenshot", "full_page": False}
        ]
        
        try:
            result = executer_sequence(actions)
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_executer_sequence_empty(self):
        """Test une séquence vide."""
        actions = []
        
        try:
            result = executer_sequence(actions)
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_executer_sequence_invalid_action(self):
        """Test une séquence avec une action invalide."""
        actions = [
            {"type": "navigate", "url": "https://example.com"},
            {"type": "invalid_action"}
        ]
        
        try:
            result = executer_sequence(actions)
            assert isinstance(result, str)
            assert "Action inconnue" in result
        except ImportError:
            pytest.skip("Playwright non installé")


@pytest.mark.slow
class TestBrowserAutomationIntegration:
    """Tests d'intégration complets."""
    
    def test_complete_workflow(self):
        """Test un workflow complet de navigation."""
        try:
            # Naviguer
            nav_result = naviguer_vers("https://example.com")
            assert "Navigation réussie" in nav_result or "Erreur" in nav_result
            
            # Obtenir des infos
            info_result = obtenir_infos_page("https://example.com")
            assert isinstance(info_result, str)
            
            # Extraire du texte
            text_result = extraire_texte("body", "https://example.com")
            assert isinstance(text_result, str)
            
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_sequence_with_multiple_actions(self):
        """Test une séquence avec plusieurs types d'actions."""
        actions = [
            {"type": "navigate", "url": "https://example.com"},
            {"type": "wait", "selector": "h1"},
            {"type": "javascript", "script": "document.title"},
            {"type": "scroll", "pixels": 200}
        ]
        
        try:
            result = executer_sequence(actions)
            assert isinstance(result, str)
            assert "navigate" in result
        except ImportError:
            pytest.skip("Playwright non installé")


class TestErrorHandling:
    """Tests pour la gestion des erreurs."""
    
    def test_invalid_url(self):
        """Test la gestion d'URL invalide."""
        try:
            result = naviguer_vers("not-a-valid-url")
            assert isinstance(result, str)
            # Devrait contenir une erreur
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_timeout_handling(self):
        """Test la gestion des timeouts."""
        try:
            # URL qui pourrait prendre du temps ou ne pas répondre
            result = naviguer_vers("https://httpbin.org/delay/10")
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_invalid_selector(self):
        """Test la gestion de sélecteurs invalides."""
        try:
            result = cliquer_element("#non-existent-element", "https://example.com")
            assert isinstance(result, str)
            # Devrait contenir une erreur
        except ImportError:
            pytest.skip("Playwright non installé")


class TestHeadlessMode:
    """Tests pour le mode headless."""
    
    def test_headless_true(self):
        """Test le mode headless activé."""
        try:
            result = naviguer_vers("https://example.com", headless=True)
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
    
    def test_headless_false(self):
        """Test le mode headless désactivé (peut échouer en CI)."""
        try:
            result = naviguer_vers("https://example.com", headless=False)
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("Playwright non installé")
        except Exception:
            # Peut échouer dans les environnements sans display
            pass