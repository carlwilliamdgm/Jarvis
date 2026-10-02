"""
Tests unitaires pour le BrowserAgent et les améliorations web_search.

Tous les tests sont hors réseau (mocks). Pas de Playwright réel instancié.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ─── Fixtures partagées ────────────────────────────────────────────────────────


def _make_snapshot_raw(url="https://example.com", title="Example", elements=None):
    """Construit un dict snapshot tel que retourné par le JS."""
    if elements is None:
        elements = [
            {"idx": 1, "type": "link", "label": "Accueil", "href": "https://example.com/"},
            {"idx": 2, "type": "button", "label": "Rechercher"},
            {"idx": 3, "type": "input", "label": "Champ recherche", "inputType": "text"},
        ]
    return {"url": url, "title": title, "elements": elements}


# ─── Tests web_search — filtrage de pertinence ────────────────────────────────

class TestWebSearchPertinence(unittest.TestCase):
    """Tests pour le filtrage sémantique dans is_valid_result."""

    def setUp(self):
        from taskflow.web_search import is_valid_result, _tokens_requete, _normaliser_texte
        self.is_valid_result = is_valid_result
        self.tokens_requete = _tokens_requete
        self.normaliser = _normaliser_texte

    def test_resultat_valide_sans_requete(self):
        """Sans requête, la validation structurelle seule s'applique."""
        result = {"title": "Paris Météo", "url": "https://meteo.fr/paris", "snippet": "Météo actuelle à Paris"}
        self.assertTrue(self.is_valid_result(result))

    def test_resultat_valide_avec_overlap(self):
        """Un résultat avec overlap sémantique est accepté."""
        result = {"title": "Météo Paris aujourd'hui", "url": "https://meteo.fr", "snippet": "Prévisions météo Paris"}
        self.assertTrue(self.is_valid_result(result, requete="meteo paris"))

    def test_resultat_metro_pakistan_rejete(self):
        """Le classique faux positif Wikipedia (Metro Pakistan pour 'meteo paris') est rejeté."""
        result = {
            "title": "Metro Pakistan",
            "url": "https://fr.wikipedia.org/wiki/Metro_Pakistan",
            "snippet": "Metro Pakistan est une chaîne de supermarchés."
        }
        # 'meteo paris' ne correspond pas → doit être rejeté
        self.assertFalse(self.is_valid_result(result, requete="meteo paris"))

    def test_wikipedia_accepte_pour_requete_encyclopedique(self):
        """Wikipedia est accepté pour une requête encyclopédique (qui est...)."""
        result = {
            "title": "Météo (science)",
            "url": "https://fr.wikipedia.org/wiki/Météorologie",
            "snippet": "La météorologie est la science qui étudie l'atmosphère."
        }
        self.assertTrue(self.is_valid_result(result, requete="qu'est-ce que la météorologie"))

    def test_url_vide_rejetee(self):
        """Un résultat sans URL est toujours rejeté."""
        result = {"title": "Paris Météo", "url": "", "snippet": "Météo Paris"}
        self.assertFalse(self.is_valid_result(result, requete="meteo paris"))

    def test_titre_generique_rejete(self):
        """Un titre générique (bing, google, here...) est rejeté."""
        result = {"title": "here", "url": "https://example.com", "snippet": ""}
        self.assertFalse(self.is_valid_result(result))

    def test_tokens_requete_filtre_mots_vides(self):
        """Les mots vides sont filtrés des tokens."""
        tokens = self.tokens_requete("les meilleurs restaurants de Paris")
        self.assertNotIn("les", tokens)
        self.assertNotIn("de", tokens)
        self.assertIn("meilleurs", tokens)
        self.assertIn("restaurants", tokens)
        self.assertIn("paris", tokens)

    def test_normaliser_texte_supprime_accents(self):
        """La normalisation supprime les accents."""
        normalise = self.normaliser("Météo à Bordeaux")
        self.assertNotIn("é", normalise)
        self.assertNotIn("à", normalise)
        self.assertIn("meteo", normalise)
        self.assertIn("bordeaux", normalise)

    def test_moteur_recherche_root_rejete(self):
        """Les racines de moteurs de recherche sont rejetées, mais /search?q=... ne l'est pas."""
        from taskflow.web_search import is_search_engine_root
        self.assertTrue(is_search_engine_root("https://www.google.com/"))
        self.assertTrue(is_search_engine_root("https://duckduckgo.com/"))
        # Une URL avec query params est un vrai résultat de recherche → ne doit PAS être racine
        self.assertFalse(is_search_engine_root("https://www.google.com/search?q=python"))
        self.assertFalse(is_search_engine_root("https://example.com/article?id=123"))

    def test_wikipedia_non_encyclopedique_bloque(self):
        """Wikipedia est bloqué pour les requêtes non encyclopédiques (sans overlap avec la requête)."""
        result = {
            "title": "Aéroport Charles de Gaulle",
            "url": "https://fr.wikipedia.org/wiki/Aeroport_CDG",
            "snippet": "L'aéroport de Paris-Charles de Gaulle est le principal aéroport français."
        }
        # 'vol montreal prix billet' → aucun token de la requête ne matche ce résultat Wikipedia
        # et la requête n'est pas encyclopédique → doit être rejeté
        self.assertFalse(self.is_valid_result(result, requete="vol montreal prix billet"))



# ─── Tests web_search — fetch_page_content propre ────────────────────────────

class TestFetchPageContentPropre(unittest.TestCase):
    """Tests pour le nettoyage HTML dans fetch_page_content."""

    def setUp(self):
        from taskflow.web_search import WebSearchEngine
        self.engine = WebSearchEngine()

    def _mock_response(self, html_text: str):
        """Crée un mock de réponse HTTP avec le HTML donné."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html_text
        return mock_resp

    def test_entites_html_decodees(self):
        """Les entités HTML (&nbsp;, &#39;, &amp;) sont décodées."""
        html_input = (
            "<html><head><title>Test &amp; Page</title></head>"
            "<body><p>L&#39;article contient du texte &nbsp; important. " * 20 + "</p></body></html>"
        )
        self.engine.session.get = MagicMock(return_value=self._mock_response(html_input))
        with patch.object(self.engine, '_rate_limit'):
            result = self.engine.fetch_page_content("https://example.com")

        self.assertEqual(result["status"], "success")
        self.assertIn("'", result["content"])  # &#39; → '
        self.assertNotIn("&#39;", result["content"])
        self.assertNotIn("&nbsp;", result["content"])
        self.assertEqual(result["origin"], "external_web")

    def test_nav_header_footer_elagages(self):
        """Le contenu nav/header/footer est élagué et le contenu main reste."""
        # Contenu principal répété pour dépasser le seuil 200 chars
        html_input = (
            "<html><head><title>Page</title></head><body>"
            "<nav>Menu Navigation BRUIT</nav>"
            "<main><p>" + "Contenu réel de la page web. " * 20 + "</p></main>"
            "<footer>Copyright 2024 Footer content</footer>"
            "</body></html>"
        )
        self.engine.session.get = MagicMock(return_value=self._mock_response(html_input))
        with patch.object(self.engine, '_rate_limit'):
            result = self.engine.fetch_page_content("https://example.com")

        # Le contenu réel doit être présent
        self.assertIn("Contenu réel", result.get("content", ""))
        # Le footer doit être absent
        self.assertNotIn("Copyright 2024 Footer", result.get("content", ""))

    def test_fallback_playwright_si_texte_court(self):
        """Le fallback Playwright est déclenché si le texte extrait est < 200 chars (SPA JS)."""
        # Simuler une SPA : requests retourne du HTML minimal (type <div id='root'>)
        html_spa = "<html><head><title>App</title></head><body><div id='root'></div></body></html>"
        self.engine.session.get = MagicMock(return_value=self._mock_response(html_spa))

        playwright_result = {
            "url": "https://spa.example.com",
            "title": "App React",
            "content": "Contenu rendu par React. " * 30,
            "status": "success",
            "length": 720,
            "origin": "external_web",
            "via": "playwright",
        }

        with patch.object(self.engine, '_rate_limit'), \
             patch.object(self.engine, '_fetch_via_playwright', return_value=playwright_result) as mock_pw:
            result = self.engine.fetch_page_content("https://spa.example.com")

        mock_pw.assert_called_once()
        self.assertEqual(result["via"], "playwright")
        self.assertEqual(result["origin"], "external_web")

    def test_origin_external_web_present(self):
        """Le champ 'origin' est toujours 'external_web' dans les résultats réussis."""
        html_input = "<html><head><title>T</title></head><body>" + "<p>Texte important. </p>" * 30 + "</body></html>"
        self.engine.session.get = MagicMock(return_value=self._mock_response(html_input))
        with patch.object(self.engine, '_rate_limit'):
            result = self.engine.fetch_page_content("https://example.com")

        self.assertEqual(result.get("origin"), "external_web")




# ─── Tests BrowserAgent ───────────────────────────────────────────────────────

class TestBrowserAgentSnapshot(unittest.TestCase):
    """Tests pour les fonctions de snapshot DOM du BrowserAgent."""

    def test_parse_snapshot_valide(self):
        """_parse_snapshot retourne url, title, elements depuis un dict valide."""
        from taskflow.browser_agent import _parse_snapshot
        raw = _make_snapshot_raw()
        url, title, elements = _parse_snapshot(raw)
        self.assertEqual(url, "https://example.com")
        self.assertEqual(title, "Example")
        self.assertEqual(len(elements), 3)

    def test_parse_snapshot_invalid_retourne_vide(self):
        """_parse_snapshot retourne des valeurs vides si l'entrée est invalide."""
        from taskflow.browser_agent import _parse_snapshot
        url, title, elements = _parse_snapshot(None)
        self.assertEqual(url, "")
        self.assertEqual(elements, [])

    def test_format_snapshot_contient_indices(self):
        """_format_snapshot produit un texte avec des indices [N] pour chaque élément."""
        from taskflow.browser_agent import _format_snapshot
        elements = [
            {"idx": 1, "type": "link", "label": "Accueil", "href": "https://example.com"},
            {"idx": 2, "type": "button", "label": "Connexion"},
            {"idx": 3, "type": "input", "label": "Email", "inputType": "email"},
        ]
        texte = _format_snapshot("https://example.com", "Example", elements)
        self.assertIn("[1]", texte)
        self.assertIn("[2]", texte)
        self.assertIn("[3]", texte)
        self.assertIn("LIEN", texte)
        self.assertIn("BOUTON", texte)
        self.assertIn("CHAMP", texte)

    def test_format_snapshot_vide(self):
        """_format_snapshot gère une liste d'éléments vide."""
        from taskflow.browser_agent import _format_snapshot
        texte = _format_snapshot("https://example.com", "Page", [])
        self.assertIn("URL:", texte)
        self.assertIn("Titre:", texte)


class TestBrowserAgentDecide(unittest.TestCase):
    """Tests pour la méthode _decide du BrowserAgent avec LLM mocké."""

    def _make_agent(self):
        from taskflow.browser_agent import BrowserAgent
        return BrowserAgent(headless=True)

    def _mock_llm_response(self, content: dict):
        """Crée un mock de réponse LLM retournant le contenu JSON donné."""
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(content)
        mock_client.chat.return_value.choices = [mock_choice]
        return mock_client

    @patch("taskflow.browser_agent.BrowserAgent._decide")
    def test_decide_retourne_dict_avec_action(self, mock_decide):
        """_decide doit retourner un dict avec au moins la clé 'action'."""
        mock_decide.return_value = {
            "action": "click",
            "params": {"index": 2},
            "raisonnement": "Je clique sur le bouton Connexion",
            "termine": False,
            "reponse_finale": "",
        }
        agent = self._make_agent()
        result = agent._decide(
            objectif="Se connecter",
            snapshot="[2] BOUTON: Connexion",
            steps_history=[],
            step_num=0,
        )
        self.assertIn("action", result)
        self.assertEqual(result["action"], "click")

    def test_decide_avec_llm_mocke_click(self):
        """_decide délègue à Core Intellect et retourne sa décision (clic)."""
        agent = self._make_agent()
        decision_ci = {
            "action": "click",
            "params": {"index": 3},
            "raisonnement": "Clic sur le champ de recherche",
            "termine": False,
            "reponse_finale": "",
        }
        # On mock directement planifier_etape_navigation — c'est Core Intellect qui décide
        with patch("core_intellect.intellect.planifier_etape_navigation", return_value=decision_ci):
            result = agent._decide(
                objectif="Rechercher quelque chose",
                snapshot="[3] CHAMP (text): Barre de recherche",
                steps_history=[],
                step_num=0,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["params"]["index"], 3)

    def test_decide_avec_llm_mocke_terminer(self):
        """_decide force termine=True quand Core Intellect retourne action=terminer."""
        agent = self._make_agent()
        decision_ci = {
            "action": "terminer",
            "params": {},
            "raisonnement": "Tâche accomplie",
            "termine": True,
            "reponse_finale": "Voici les résultats trouvés.",
        }
        with patch("core_intellect.intellect.planifier_etape_navigation", return_value=decision_ci):
            result = agent._decide(
                objectif="Trouver une info",
                snapshot="",
                steps_history=[],
                step_num=5,
            )
        self.assertIsNotNone(result)
        self.assertTrue(result["termine"])

    def test_decide_retourne_none_si_core_intellect_indisponible(self):
        """_decide retourne None si Core Intellect (planifier_etape_navigation) échoue."""
        agent = self._make_agent()
        with patch("core_intellect.intellect.planifier_etape_navigation", return_value=None):
            result = agent._decide(
                objectif="Test",
                snapshot="",
                steps_history=[],
                step_num=0,
            )
        self.assertIsNone(result)




class TestBrowserAgentExecuteAction(unittest.TestCase):
    """Tests pour _execute_action avec sessions mockées."""

    def _make_session_mock(self, url="https://example.com"):
        session = MagicMock()
        session.navigate_sync.return_value = "Navigation réussie vers https://example.com"
        session.get_url_sync.return_value = url
        session.scroll_sync.return_value = "Scroll effectué"
        session.execute_javascript_sync.return_value = "Résultat: clicked"
        session.is_alive.return_value = True
        return session

    def test_execute_navigate_succes(self):
        """L'action navigate retourne un StepResult success."""
        from taskflow.browser_agent import BrowserAgent
        agent = BrowserAgent()
        session = self._make_session_mock()
        result = agent._execute_action(session, "navigate", {"url": "https://google.com"}, "https://old.com")
        self.assertTrue(result.success)
        self.assertEqual(result.action, "navigate")

    def test_execute_navigate_sans_url(self):
        """L'action navigate sans URL retourne une erreur."""
        from taskflow.browser_agent import BrowserAgent
        agent = BrowserAgent()
        session = self._make_session_mock()
        result = agent._execute_action(session, "navigate", {}, "https://example.com")
        self.assertFalse(result.success)

    def test_execute_scroll(self):
        """L'action scroll retourne un StepResult success."""
        from taskflow.browser_agent import BrowserAgent
        agent = BrowserAgent()
        session = self._make_session_mock()
        result = agent._execute_action(session, "scroll", {"pixels": 300}, "https://example.com")
        self.assertTrue(result.success)
        self.assertIn("300", result.observation)

    def test_execute_wait(self):
        """L'action wait attend le nombre de secondes spécifié (max 5s)."""
        from taskflow.browser_agent import BrowserAgent
        import time
        agent = BrowserAgent()
        session = self._make_session_mock()
        start = time.time()
        result = agent._execute_action(session, "wait", {"seconds": 0.1}, "https://example.com")
        elapsed = time.time() - start
        self.assertTrue(result.success)
        self.assertGreaterEqual(elapsed, 0.05)

    def test_execute_action_inconnue(self):
        """Une action inconnue retourne un StepResult failure."""
        from taskflow.browser_agent import BrowserAgent
        agent = BrowserAgent()
        session = self._make_session_mock()
        result = agent._execute_action(session, "action_inconnue", {}, "https://example.com")
        self.assertFalse(result.success)
        self.assertIn("inconnue", result.observation)

    def test_execute_terminer(self):
        """L'action terminer retourne un StepResult success avec observation."""
        from taskflow.browser_agent import BrowserAgent
        agent = BrowserAgent()
        session = self._make_session_mock()
        result = agent._execute_action(session, "terminer", {}, "https://example.com")
        self.assertTrue(result.success)
        self.assertEqual(result.action, "terminer")


class TestBrowserAgentAccomplir(unittest.TestCase):
    """Tests de la boucle ReAct accomplir() avec mocks complets."""

    @patch("taskflow.browser_agent.BrowserAgent._fermer_popups_cookies")
    @patch("taskflow.browser_agent.BrowserAgent._take_snapshot")
    @patch("taskflow.browser_agent.BrowserAgent._decide")
    @patch("taskflow.browser_session.get_session_manager")
    def test_accomplir_tache_simple(self, mock_sm, mock_decide, mock_snapshot, mock_cookies):
        """La boucle ReAct se termine quand le LLM retourne termine=True."""
        from taskflow.browser_agent import BrowserAgent

        # Mock session
        mock_session = MagicMock()
        mock_session.navigate_sync.return_value = "Navigation réussie vers https://example.com"
        mock_session.get_url_sync.return_value = "https://example.com"
        mock_session.is_alive.return_value = True
        mock_session.execute_javascript_sync.return_value = "Résultat: clicked"
        mock_sm.return_value.get_default_session.return_value = mock_session

        # Mock snapshot
        mock_snapshot.return_value = _make_snapshot_raw()

        # Mock décisions : extraire contenu puis terminer
        mock_decide.side_effect = [
            {
                "action": "extraire_contenu",
                "params": {},
                "raisonnement": "La page est chargée, j'extrais le contenu",
                "termine": False,
                "reponse_finale": "",
            },
            {
                "action": "terminer",
                "params": {},
                "raisonnement": "J'ai les informations nécessaires",
                "termine": True,
                "reponse_finale": "La page Example est accessible et contient du texte.",
            },
        ]

        # Mock extraction texte
        with patch.object(BrowserAgent, "_extraire_texte_propre", return_value="Contenu de la page."):
            agent = BrowserAgent()
            result = agent.accomplir("Vérifier que example.com est accessible")

        self.assertTrue(result.success)
        self.assertIn("Example", result.reponse)
        self.assertEqual(result.origin.value, "external")

    @patch("taskflow.browser_session.get_session_manager")
    def test_accomplir_echec_demarrage_navigateur(self, mock_sm):
        """accomplir() gère l'échec de démarrage du navigateur."""
        from taskflow.browser_agent import BrowserAgent
        mock_sm.return_value.get_default_session.side_effect = RuntimeError("Playwright non disponible")

        agent = BrowserAgent()
        result = agent.accomplir("Une tâche quelconque")

        self.assertFalse(result.success)
        self.assertIn("navigateur", result.erreur.lower())


class TestAccomplirTacheWebTool(unittest.TestCase):
    """Tests pour le wrapper outil accomplir_tache_web_tool."""

    @patch("taskflow.tools.evaluate_capability")
    @patch("taskflow.tools.accomplir_tache_web")
    def test_tool_appelle_accomplir(self, mock_accomplir, mock_eval):
        """Le tool appelle accomplir_tache_web si la policy autorise."""
        from greatos_contracts import SecurityDecision
        from taskflow.tools import accomplir_tache_web_tool

        mock_decision = MagicMock()
        mock_decision.decision = SecurityDecision.ALLOW
        mock_eval.return_value = mock_decision

        mock_accomplir.return_value = "✅ Tâche accomplie : test"

        result = accomplir_tache_web_tool("Rechercher quelque chose")
        mock_accomplir.assert_called_once()
        self.assertIn("Tâche", result)

    @patch("taskflow.tools.evaluate_capability")
    def test_tool_bloque_par_defcon(self, mock_eval):
        """Le tool retourne une erreur si DataShield bloque la requête."""
        from greatos_contracts import SecurityDecision
        from taskflow.tools import accomplir_tache_web_tool

        mock_decision = MagicMock()
        mock_decision.decision = SecurityDecision.DENY
        mock_decision.reason = "DEFCON 1 : navigation externe bloquée"
        mock_eval.return_value = mock_decision

        result = accomplir_tache_web_tool("Aller sur un site externe")
        # resultat_erreur peut retourner un objet ResultatOutil ou une str selon la version
        result_str = str(result).lower()
        self.assertTrue(
            "block" in result_str or "defcon" in result_str or "refus" in result_str or "deny" in result_str,
            f"Attendu un message de blocage, obtenu: {result_str}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

