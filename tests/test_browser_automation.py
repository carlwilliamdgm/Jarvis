"""
Tests pour le module d automatisation de navigateur.
Compatibles avec unittest (py -3.12 -m unittest discover -s tests).
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from taskflow.browser_automation import (
    BrowserAutomation,
    BrowserType,
    naviguer_vers,
    cliquer_element,
    remplir_formulaire,
    extraire_texte,
    prendre_capture,
    executer_sequence,
    obtenir_infos_page,
    fermer_navigateur,
    reinitialiser_navigateur,
)
from taskflow.browser_session import BrowserSessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAYWRIGHT_AVAILABLE: bool
try:
    import playwright  # noqa: F401
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

requires_playwright = unittest.skipUnless(
    PLAYWRIGHT_AVAILABLE, "Playwright non installe - test ignore"
)


# ---------------------------------------------------------------------------
# Tests unitaires BrowserType / BrowserAutomation
# ---------------------------------------------------------------------------

class TestBrowserType(unittest.TestCase):

    def test_chromium_value(self):
        self.assertEqual(BrowserType.CHROMIUM.value, "chromium")

    def test_firefox_value(self):
        self.assertEqual(BrowserType.FIREFOX.value, "firefox")

    def test_webkit_value(self):
        self.assertEqual(BrowserType.WEBKIT.value, "webkit")


class TestBrowserAutomationInit(unittest.TestCase):

    def test_defaults(self):
        browser = BrowserAutomation(headless=True, browser_type=BrowserType.CHROMIUM)
        self.assertTrue(browser.headless)
        self.assertEqual(browser.browser_type, BrowserType.CHROMIUM)
        self.assertIsNone(browser.browser)
        self.assertIsNone(browser.page)

    def test_headless_false(self):
        browser = BrowserAutomation(headless=False)
        self.assertFalse(browser.headless)


# ---------------------------------------------------------------------------
# Tests BrowserSessionManager (mocke)
# ---------------------------------------------------------------------------

class TestBrowserSessionManagerMocked(unittest.TestCase):

    def _make_mock_session(self):
        session = MagicMock()
        session.is_alive.return_value = True
        session.navigate_sync.return_value = "Navigation reussie vers https://example.com"
        session.get_text_sync.return_value = "Exemple de texte"
        session.screenshot_sync.return_value = "data:image/png;base64,AAAA"
        session.get_info_sync.return_value = {"url": "https://example.com", "title": "Example Domain"}
        session.click_sync.return_value = "Clic effectue"
        session.fill_sync.return_value = "Champ rempli"
        session.execute_javascript_sync.return_value = "Example Domain"
        return session

    def test_navigate_sync_called(self):
        session = self._make_mock_session()
        result = session.navigate_sync("https://example.com")
        self.assertIn("Navigation", result)
        session.navigate_sync.assert_called_once_with("https://example.com")

    def test_screenshot_sync_returns_base64(self):
        session = self._make_mock_session()
        result = session.screenshot_sync()
        self.assertIn("data:image/png;base64", result)

    def test_get_text_sync_returns_string(self):
        session = self._make_mock_session()
        result = session.get_text_sync("body")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_session_is_alive(self):
        session = self._make_mock_session()
        self.assertTrue(session.is_alive())

    def test_persistent_session_reuse(self):
        """Le meme objet session est retourne si deja vivant."""
        manager = BrowserSessionManager()
        mock_session = self._make_mock_session()
        with patch.object(manager, "get_default_session", return_value=mock_session):
            s1 = manager.get_default_session()
            s2 = manager.get_default_session()
        self.assertIs(s1, s2)


# ---------------------------------------------------------------------------
# Tests fonctions synchrones (session persistante mockee)
# ---------------------------------------------------------------------------

class TestBrowserAutomationFunctionsMocked(unittest.TestCase):

    def _make_session(self):
        session = MagicMock()
        session.navigate_sync.return_value = "Navigation reussie vers https://example.com"
        session.get_text_sync.return_value = "Contenu de la page"
        session.screenshot_sync.return_value = "data:image/png;base64,AAAA"
        session.get_info_sync.return_value = "INFORMATIONS PAGE\nURL: https://example.com\nTitle: Example Domain"
        session.get_url_sync.return_value = "https://example.com"
        session.click_sync.return_value = "Clic effectue sur #btn"
        session.fill_sync.return_value = "Champ #input rempli"
        return session

    def _patch_session(self, session):
        return patch("taskflow.browser_automation._get_persistent_session", return_value=session)

    def test_naviguer_vers_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = naviguer_vers("https://example.com")
        self.assertIsInstance(result, str)

    def test_naviguer_vers_calls_navigate_sync(self):
        session = self._make_session()
        with self._patch_session(session):
            naviguer_vers("https://example.com")
        session.navigate_sync.assert_called_once()

    def test_extraire_texte_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = extraire_texte("body")
        self.assertIsInstance(result, str)

    def test_prendre_capture_returns_base64(self):
        session = self._make_session()
        with self._patch_session(session):
            result = prendre_capture()
        self.assertIn("data:image/png;base64", result)

    def test_cliquer_element_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = cliquer_element("#btn")
        self.assertIsInstance(result, str)

    def test_remplir_formulaire_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = remplir_formulaire("#input", "valeur")
        self.assertIsInstance(result, str)

    def test_obtenir_infos_page_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = obtenir_infos_page()
        self.assertIsInstance(result, str)

    def test_executer_sequence_empty_returns_string(self):
        session = self._make_session()
        with self._patch_session(session):
            result = executer_sequence([])
        self.assertIsInstance(result, str)

    def test_executer_sequence_navigate_action(self):
        session = self._make_session()
        actions = [{"type": "navigate", "url": "https://example.com"}]
        with self._patch_session(session):
            result = executer_sequence(actions)
        self.assertIsInstance(result, str)

    def test_executer_sequence_unknown_action(self):
        session = self._make_session()
        actions = [{"type": "unknown_action_xyz"}]
        with self._patch_session(session):
            result = executer_sequence(actions)
        self.assertIsInstance(result, str)
        self.assertIn("Action inconnue", result)

    def test_fermer_navigateur_returns_string(self):
        result = fermer_navigateur()
        self.assertIsInstance(result, str)

    def test_reinitialiser_navigateur_returns_string(self):
        result = reinitialiser_navigateur()
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# Tests integration (Playwright requis)
# ---------------------------------------------------------------------------

@requires_playwright
class TestBrowserAutomationIntegration(unittest.TestCase):

    def tearDown(self):
        try:
            fermer_navigateur()
        except Exception:
            pass

    def test_naviguer_vers_example(self):
        result = naviguer_vers("https://example.com")
        self.assertIsInstance(result, str)

    def test_obtenir_infos_page_example(self):
        result = obtenir_infos_page("https://example.com")
        self.assertIsInstance(result, str)
        if "Erreur" not in result:
            self.assertIn("INFORMATIONS PAGE", result)

    def test_extraire_texte_example(self):
        result = extraire_texte("body", "https://example.com")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
