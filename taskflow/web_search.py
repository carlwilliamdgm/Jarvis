"""
Module de recherche web avancée pour Jarvis.

Ce module permet à Jarvis d'effectuer des recherches web intelligentes,
avec extraction propre du contenu (décodage HTML, élagage navigation),
filtrage de pertinence sémantique et fallback Playwright pour les SPAs JS.
"""

import html as _html_module
import logging
import re
import json
import time
import os
import unicodedata
from typing import List, Dict, Optional, Any
from urllib.parse import urlencode, quote_plus, urlparse
import requests

# ─── Constantes de pertinence ─────────────────────────────────────────────────

# Requêtes encyclopédiques → Wikipedia reste pertinent même sans overlap strict
_INTENT_ENCYCLOPEDIQUE = re.compile(
    r"\b(qu(?:i|'est|oi)|what|who|when|quand|o[uù]|where|histoire|history|"
    r"d[ée]finition|definition|biographie|biography|wikipedia|signification|"
    r"meaning|origine|origin)\b",
    re.IGNORECASE,
)

# Nombre minimum de tokens de la requête devant apparaître dans title+snippet
_MIN_TOKEN_OVERLAP = 1

logger = logging.getLogger(__name__)

# Tentative d'import de ddgs (paquet officiel moderne) ou duckduckgo-search (legacy)
try:
    from ddgs import DDGS
    DDG_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        DDG_AVAILABLE = True
    except ImportError:
        DDG_AVAILABLE = False

SEARCH_ENGINE_ROOTS = {
    "duckduckgo.com", "html.duckduckgo.com",
    "google.com", "google.fr",
    "bing.com",
    "yahoo.com",
    "qwant.com",
    "ecosia.org",
    "brave.com",
}


def is_search_engine_root(url: str) -> bool:
    """Vérifie si une URL pointe vers la racine ou une redirection interne d'un moteur de recherche."""
    if not url:
        return True
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.strip('/')
        # Une URL avec query params n'est pas une racine de moteur (c'est un vrai résultat)
        if parsed.query:
            return False
        for root in SEARCH_ENGINE_ROOTS:
            if netloc == root or netloc.endswith("." + root):
                if not path or path in ('', 'html', 'l'):
                    return True
    except Exception:
        pass
    return False



def _normaliser_texte(texte: str) -> str:
    """Normalise un texte : minuscules, sans accents, sans ponctuation."""
    texte = texte.lower()
    # Supprimer les accents
    nfkd = unicodedata.normalize('NFKD', texte)
    texte = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Garder seulement lettres et espaces
    texte = re.sub(r'[^a-z0-9\s]', ' ', texte)
    return texte


def _tokens_requete(requete: str) -> list[str]:
    """
    Extrait les tokens significatifs d'une requête (longueur >= 3, hors mots vides).
    """
    MOTS_VIDES = {
        "les", "des", "une", "qui", "que", "quoi", "pour", "avec", "dans",
        "sur", "par", "the", "and", "for", "how", "are", "was",
    }
    tokens = _normaliser_texte(requete).split()
    return [t for t in tokens if len(t) >= 3 and t not in MOTS_VIDES]


def is_valid_result(result: Dict[str, Any], requete: str = "") -> bool:
    """
    Valide qu'un résultat est structurellement valide ET sémantiquement pertinent.

    Args:
        result: Dictionnaire résultat avec clés 'title', 'url', 'snippet'.
        requete: Requête originale pour le filtrage de pertinence. Si vide, seule
                 la validation structurelle est effectuée.

    Returns:
        True si le résultat est valide et pertinent.
    """
    if not isinstance(result, dict):
        return False

    title = (result.get("title") or "").strip().lower()
    url = (result.get("url") or "").strip()

    # Validation structurelle
    if not url or is_search_engine_root(url):
        return False
    if title in {"here", "sans titre", "duckduckgo", "google", "bing", "error", "temporairement indisponible"}:
        return False
    if "temporairement indisponible" in title:
        return False

    # Filtrage de pertinence sémantique (seulement si une requête est fournie)
    if requete:
        tokens = _tokens_requete(requete)
        if tokens:
            snippet = (result.get("snippet") or "").lower()
            texte_result = _normaliser_texte(f"{title} {snippet}")
            overlap = sum(1 for t in tokens if t in texte_result)
            if overlap < _MIN_TOKEN_OVERLAP:
                # Wikipedia : n'accepter que pour les intentions encyclopédiques
                is_wiki = "wikipedia.org" in url
                if is_wiki and not _INTENT_ENCYCLOPEDIQUE.search(requete):
                    logger.debug("Résultat Wikipedia rejeté (non encyclopédique): %s", title)
                    return False
                if not is_wiki:
                    logger.debug("Résultat rejeté (pertinence insuffisante, overlap=%d): %s", overlap, title)
                    return False

    return True





class WebSearchEngine:
    """Moteur de recherche web avec support pour plusieurs providers."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.last_request_time = 0
        self.min_request_interval = 1.0  # 1 seconde entre les requêtes
        
        # Configuration des providers
        self.brave_api_key = os.environ.get("BRAVE_API_KEY")
        # Utiliser duckduckgo-search si disponible, sinon DuckDuckGo API
        self.preferred_provider = "brave" if self.brave_api_key else ("duckduckgo_search" if DDG_AVAILABLE else "duckduckgo")
    
    def _rate_limit(self):
        """Applique une limitation de taux entre les requêtes."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()
    
    def search_brave(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """
        Effectue une recherche via Brave Search API.
        
        Brave offre 2000 requêtes/mois gratuites.
        """
        if not self.brave_api_key:
            return []
        
        self._rate_limit()
        
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip',
                'X-Subscription-Token': self.brave_api_key
            }
            params = {
                'q': query,
                'count': num_results
            }
            
            response = self.session.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # Extraire les résultats web
            if 'web' in data and 'results' in data['web']:
                for item in data['web']['results'][:num_results]:
                    results.append({
                        "title": item.get('title', ''),
                        "url": item.get('url', ''),
                        "snippet": item.get('description', '')
                    })
            
            return results
            
        except Exception as e:
            # Fallback vers DuckDuckGo en cas d'erreur
            return self.search_duckduckgo(query, num_results)
    
    def search_google(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """
        Effectue une recherche via Google (requiert API key ou utilise une méthode alternative).
        
        Pour l'instant, utilise Brave comme alternative gratuite.
        """
        return self.search_brave(query, num_results)
    
    def search_duckduckgo(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """
        Effectue une recherche via DuckDuckGo (gratuit, pas d'API key requise).
        """
        self._rate_limit()
        
        try:
            # Utilise l'API JSON de DuckDuckGo Instant Answer API
            url = "https://api.duckduckgo.com/"
            params = {
                'q': query,
                'format': 'json',
                'no_html': 1,
                'skip_disambig': 0
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # DuckDuckGo Instant Answer API ne retourne pas une liste de résultats classiques
            # On utilise les RelatedTopics si disponibles
            if 'RelatedTopics' in data:
                for topic in data['RelatedTopics'][:num_results]:
                    if isinstance(topic, dict) and 'FirstURL' in topic:
                        results.append({
                            "title": topic.get('Text', topic.get('FirstURL', 'Sans titre')).split(' - ')[0],
                            "url": topic['FirstURL'],
                            "snippet": topic.get('Text', '')
                        })
            
            # Si aucun résultat, essayer l'approche HTML
            if not results:
                return self._search_duckduckgo_html(query, num_results)
            
            return results
            
        except Exception as e:
            # Fallback vers la méthode HTML
            return self._search_duckduckgo_html(query, num_results)
    
    def search_duckduckgo_search(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """
        Utilise la bibliothèque ddgs (ou duckduckgo-search).
        
        Cette bibliothèque est la solution communautaire maintenue pour interroger l'API DuckDuckGo.
        """
        if not DDG_AVAILABLE:
            return []
        
        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=num_results))
            results = []
            for result in raw_results:
                item = {
                    "title": (result.get('title') or '').strip(),
                    "url": (result.get('href') or '').strip(),
                    "snippet": (result.get('body') or '').strip()
                }
                if is_valid_result(item):
                    results.append(item)
            return results
        except Exception as e:
            logger.warning("Échec ddgs (%s): %s", query, e)
            return []
    
    def search_wikipedia(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Recherche des articles sur Wikipedia français en fallback fiable.
        Ne nécessite aucune clé API.
        """
        self._rate_limit()
        try:
            url = "https://fr.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'generator': 'search',
                'gsrsearch': query,
                'gsrlimit': min(num_results, 10),
                'prop': 'extracts|info',
                'exintro': 1,
                'explaintext': 1,
                'inprop': 'url',
                'format': 'json'
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            pages = data.get('query', {}).get('pages', {})
            results = []
            for _, page_info in pages.items():
                title = (page_info.get('title') or '').strip()
                page_url = (page_info.get('fullurl') or '').strip()
                extract = (page_info.get('extract') or '').strip()
                if title and page_url:
                    item = {
                        "title": title,
                        "url": page_url,
                        "snippet": extract[:300] if extract else ""
                    }
                    if is_valid_result(item):
                        results.append(item)
            return results
        except Exception as e:
            logger.warning("Échec Wikipedia (%s): %s", query, e)
            return []

    def search(self, query: str, num_results: int = 10, provider: str = None) -> List[Dict[str, Any]]:
        """
        Effectue une recherche web avec le provider approprié et cascade de secours.

        Ordre de cascade :
        1. Brave (si configuré ou demandé)
        2. ddgs (duckduckgo_search)
        3. DuckDuckGo Instant Answer / HTML
        4. Wikipedia Search API (uniquement pour requêtes encyclopédiques)

        Args:
            query: La requête de recherche
            num_results: Nombre de résultats souhaités
            provider: Provider spécifique ('brave', 'duckduckgo_search', 'duckduckgo', 'wikipedia', None pour auto)

        Returns:
            Liste de résultats valides et pertinents avec titre, URL et snippet
        """
        # 1. Provider Brave explicite ou prioritaire
        if (provider == "brave" or (provider is None and self.preferred_provider == "brave")) and self.brave_api_key:
            results = [r for r in self.search_brave(query, num_results) if is_valid_result(r, query)]
            if results:
                return results

        # 2. ddgs (duckduckgo_search)
        if (provider in (None, "duckduckgo_search", "ddgs")) and DDG_AVAILABLE:
            results = [r for r in self.search_duckduckgo_search(query, num_results) if is_valid_result(r, query)]
            if results:
                return results

        # 3. DuckDuckGo API classique ou HTML
        if provider in (None, "duckduckgo"):
            results = [r for r in self.search_duckduckgo(query, num_results) if is_valid_result(r, query)]
            if results:
                return results

        # 4. Fallback Wikipedia — uniquement pour requêtes encyclopédiques
        if _INTENT_ENCYCLOPEDIQUE.search(query):
            wiki_results = [r for r in self.search_wikipedia(query, min(num_results, 5)) if is_valid_result(r, query)]
            if wiki_results:
                return wiki_results

        return []

    
    def _search_duckduckgo_html(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """Méthode de fallback utilisant le HTML de DuckDuckGo avec parsing amélioré."""
        params = {
            'q': query,
            'kl': 'fr-fr',
        }
        
        try:
            url = "https://html.duckduckgo.com/html/"
            response = self.session.post(url, data=params, timeout=10)
            response.raise_for_status()
            
            results = self._parse_duckduckgo_html(response.text, num_results)
            results = [r for r in results if is_valid_result(r)]
            
            # Si toujours aucun résultat, essayer l'approche alternative
            if not results:
                return self._search_duckduckgo_v2(query, num_results)
            
            return results
            
        except Exception as e:
            logger.debug("Échec _search_duckduckgo_html: %s", e)
            return self._search_duckduckgo_v2(query, num_results)
    
    def _search_duckduckgo_v2(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """Approche alternative pour DuckDuckGo avec différents patterns."""
        try:
            params = {
                'q': query,
            }
            url = "https://duckduckgo.com/"
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            results = self._parse_duckduckgo_alternative(response.text, num_results)
            return [r for r in results if is_valid_result(r)]
            
        except Exception as e:
            logger.debug("Échec _search_duckduckgo_v2: %s", e)
            return []
    
    def _parse_duckduckgo_html(self, html: str, num_results: int) -> List[Dict[str, Any]]:
        """Parse les résultats HTML de DuckDuckGo."""
        results = []
        
        patterns = [
            r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>',
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
            r'<a[^>]*href="([^"]+)"[^>]*class="result__a"[^>]*>([^<]+)</a>',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                for url, title in matches[:num_results]:
                    clean_url = self._clean_duckduckgo_url(url)
                    snippet_pattern = r'<a[^>]*result__a[^>]*>.*?</a>.*?<a[^>]*class="result__snippet"[^>]*>([^<]+)</a>'
                    snippet_match = re.search(snippet_pattern, html, re.IGNORECASE | re.DOTALL)
                    snippet = snippet_match.group(1).strip() if snippet_match else ""
                    
                    item = {
                        "title": title.strip(),
                        "url": clean_url,
                        "snippet": snippet
                    }
                    if is_valid_result(item):
                        results.append(item)
                break
        
        if not results:
            all_links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html, re.IGNORECASE)
            for url, title in all_links[:num_results]:
                clean_url = self._clean_duckduckgo_url(url)
                item = {
                    "title": title.strip(),
                    "url": clean_url,
                    "snippet": ""
                }
                if is_valid_result(item):
                    results.append(item)
        
        return results
    
    def _parse_duckduckgo_alternative(self, html: str, num_results: int) -> List[Dict[str, Any]]:
        """Approche alternative de parsing pour DuckDuckGo avec patterns plus génériques."""
        results = []
        
        alternative_patterns = [
            r'<a[^>]*class="[^"]*result[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
            r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?</h2>',
            r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>([^<]{5,100})</a>',
        ]
        
        for pattern in alternative_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            if matches:
                for url, title in matches[:num_results]:
                    clean_url = self._clean_duckduckgo_url(url)
                    item = {
                        "title": title.strip(),
                        "url": clean_url,
                        "snippet": ""
                    }
                    if is_valid_result(item):
                        results.append(item)
                if results:
                    break
        
        return results
    
    def _clean_duckduckgo_url(self, url: str) -> str:
        """Nettoie les URLs redirect de DuckDuckGo."""
        if "duckduckgo.com/l/?uddg=" in url:
            try:
                # Extraire l'URL réelle du redirect
                start = url.find("uddg=") + 5
                end = url.find("&", start)
                if end == -1:
                    end = len(url)
                import urllib.parse
                return urllib.parse.unquote(url[start:end])
            except Exception as e:
                logger.debug("Échec nettoyage URL DuckDuckGo '%s': %s", url, e)
                return url
        return url
    
    def fetch_page_content(self, url: str, max_length: int = 10000) -> Dict[str, Any]:
        """
        Récupère et extrait le contenu textuel propre d'une page web.

        Améliorations par rapport à la version précédente :
        - Décodage des entités HTML (html.unescape) → plus de &nbsp; ni &#39;
        - Élagage des blocs de bruit : <nav>, <header>, <footer>, <aside>
        - Fallback Playwright automatique si le texte extrait < 200 caractères
          (page SPA React/Vue/Angular avec rendu JS requis)
        - Champ 'origin' = 'external_web' pour le Taint DataShield

        Args:
            url: URL de la page à récupérer
            max_length: Longueur maximale du contenu à retourner

        Returns:
            Dictionnaire avec titre, contenu propre, url, status, length, origin
        """
        self._rate_limit()

        def _extraire_texte_propre(html_raw: str) -> tuple[str, str]:
            """Retourne (titre, texte_propre) depuis du HTML brut."""
            # Titre
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html_raw, re.IGNORECASE)
            titre = _html_module.unescape(title_match.group(1).strip()) if title_match else "Sans titre"

            # Supprimer scripts, styles, commentaires
            raw = re.sub(r'<script[^>]*>.*?</script>', ' ', html_raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r'<!--.*?-->', ' ', raw, flags=re.DOTALL)

            # Élaguer les blocs de bruit de navigation/structure
            for bruit in ('nav', 'header', 'footer', 'aside'):
                raw = re.sub(
                    rf'<{bruit}[^>]*>.*?</{bruit}>',
                    ' ',
                    raw,
                    flags=re.DOTALL | re.IGNORECASE,
                )

            # Supprimer les balises restantes
            texte = re.sub(r'<[^>]+>', ' ', raw)

            # Décoder les entités HTML
            texte = _html_module.unescape(texte)

            # Normaliser les espaces blancs
            texte = re.sub(r'[ \t]+', ' ', texte)
            texte = re.sub(r'\n{3,}', '\n\n', texte)
            texte = texte.strip()

            return titre, texte

        # ── Tentative 1 : requests (rapide, sites HTML statiques) ─────────────
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            titre, texte = _extraire_texte_propre(response.text)

            # Détecter une SPA (page vide après nettoyage) → fallback Playwright
            if len(texte) >= 200:
                if len(texte) > max_length:
                    texte = texte[:max_length] + "..."
                return {
                    "url": url,
                    "title": titre,
                    "content": texte,
                    "status": "success",
                    "length": len(texte),
                    "origin": "external_web",
                }
            logger.debug("Contenu trop court (%d chars) pour %s → fallback Playwright", len(texte), url)

        except requests.RequestException as e:
            logger.debug("Erreur requests pour %s: %s → tentative Playwright", url, e)

        # ── Tentative 2 : Playwright headless (SPAs JS, React/Vue/Angular) ────
        try:
            return self._fetch_via_playwright(url, max_length)
        except Exception as e:
            logger.warning("Playwright fetch échoué pour %s: %s", url, e)
            return {
                "url": url,
                "error": f"Impossible d'extraire le contenu (requests + Playwright): {str(e)}",
                "status": "error",
                "origin": "external_web",
            }

    def _fetch_via_playwright(self, url: str, max_length: int = 10000) -> Dict[str, Any]:
        """
        Récupère le contenu d'une page via Playwright headless (pour les SPAs JS).

        Utilise la session de navigateur persistante de Jarvis.
        """
        from taskflow.browser_session import get_session_manager
        session = get_session_manager().get_default_session(headless=True)

        nav_result = session.navigate_sync(url, timeout=40.0)
        if "erreur" in nav_result.lower():
            raise RuntimeError(nav_result)

        # Attendre que le contenu JS soit chargé
        import time as _time
        _time.sleep(1.5)

        # Extraire le titre
        titre = session.get_title_sync()

        # Extraire le texte depuis le body (élagage côté navigateur)
        _js_extract = r"""
(function() {
    var noisy = ['nav', 'header', 'footer', 'aside'];
    noisy.forEach(function(tag) {
        document.querySelectorAll(tag).forEach(function(el) { el.remove(); });
    });
    var main = document.querySelector('main, article, [role="main"]') || document.body;
    return (main.innerText || main.textContent || '').replace(/\s+/g, ' ').trim().substring(0, 12000);
})();
"""
        raw = session.execute_javascript_sync(_js_extract, timeout=15.0)
        if isinstance(raw, str) and raw.startswith("Résultat: "):
            raw = raw[len("Résultat: "):]
        try:
            import json as _json
            texte = _json.loads(raw) if raw.startswith('"') else raw
        except Exception:
            texte = raw

        texte = str(texte).strip()
        if len(texte) > max_length:
            texte = texte[:max_length] + "..."

        return {
            "url": url,
            "title": titre or "Sans titre",
            "content": texte,
            "status": "success",
            "length": len(texte),
            "origin": "external_web",
            "via": "playwright",
        }




def rechercher_web(requete: str, nombre_resultats: int = 5) -> str:
    """
    Effectue une recherche web et retourne les résultats.
    
    Args:
        requete: La requête de recherche
        nombre_resultats: Nombre de résultats à retourner (max 10)
        
    Returns:
        Résultats de recherche formatés
    """
    engine = WebSearchEngine()
    results = engine.search(requete, min(nombre_resultats, 10))
    
    # Filtrer strictement les résultats factices ou invalides
    filtered_results = [r for r in results if is_valid_result(r)]
    if not filtered_results:
        return f"Erreur lors de la recherche: aucun résultat fiable trouvé pour '{requete}'. Vérifiez votre connexion ou configurez une clé API Brave Search (BRAVE_API_KEY)."
    
    # Utiliser les résultats filtrés pour le formatage
    lignes = [f"=== RÉSULTATS DE RECHERCHE: {requete} ==="]
    lignes.append(f"{len(filtered_results)} résultats trouvés\n")
    
    for i, result in enumerate(filtered_results, 1):
        lignes.append(f"{i}. {result.get('title', 'Sans titre')}")
        lignes.append(f"   URL: {result.get('url', 'N/A')}")
        if result.get('snippet'):
            lignes.append(f"   {result.get('snippet')}")
        lignes.append("")
    
    return "\n".join(lignes)


def analyser_page_web(url: str) -> str:
    """
    Analyse et extrait le contenu d'une page web.
    
    Args:
        url: URL de la page à analyser
        
    Returns:
        Contenu extrait et analysé de la page
    """
    engine = WebSearchEngine()
    page_data = engine.fetch_page_content(url)
    
    if page_data.get("status") == "error":
        return f"Erreur: {page_data.get('error')}"
    
    lignes = [f"=== ANALYSE DE LA PAGE: {url} ==="]
    lignes.append(f"Titre: {page_data.get('title', 'Sans titre')}")
    lignes.append(f"Longueur du contenu: {page_data.get('length', 0)} caractères")
    lignes.append("\n--- CONTENU ---")
    lignes.append(page_data.get('content', 'Aucun contenu extrait'))
    
    return "\n".join(lignes)


def rechercher_et_analyser(requete: str, nombre_pages: int = 3) -> str:
    """
    Effectue une recherche web et analyse le contenu des pages les plus pertinentes.
    
    Args:
        requete: La requête de recherche
        nombre_pages: Nombre de pages à analyser en détail
        
    Returns:
        Synthèse de la recherche avec analyse des contenus
    """
    engine = WebSearchEngine()
    results = [r for r in engine.search(requete, nombre_pages * 2) if is_valid_result(r)]
    
    if not results:
        return f"Erreur lors de la recherche: aucun résultat fiable trouvé pour '{requete}'."
    
    lignes = [f"=== RÉSULTATS DE RECHERCHE: {requete} ==="]
    lignes.append(f"{len(results)} résultats trouvés\n")
    for i, result in enumerate(results, 1):
        lignes.append(f"{i}. {result.get('title', 'Sans titre')}")
        lignes.append(f"   URL: {result.get('url', 'N/A')}")
        if result.get('snippet'):
            lignes.append(f"   {result.get('snippet')}")
        lignes.append("")
    
    lignes.append("\n=== ANALYSE DES PAGES PERTINENTES ===\n")
    
    for i, result in enumerate(results[:nombre_pages], 1):
        url = result.get('url', '')
        if url and not is_search_engine_root(url):
            lignes.append(f"\n--- Page {i}: {result.get('title', 'Sans titre')} ---")
            page_analysis = analyser_page_web(url)
            lignes.append(page_analysis)
    
    return "\n".join(lignes)


def extraire_informations_cles(texte: str) -> str:
    """
    Extrait les informations clés d'un texte (nombres, dates, emails, URLs).
    
    Args:
        texte: Le texte à analyser
        
    Returns:
        Informations clés extraites
    """
    lignes = ["=== INFORMATIONS CLÉS EXTRAITES ==="]
    
    # Extraire les URLs
    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', texte)
    if urls:
        lignes.append(f"\nURLs trouvées ({len(urls)}):")
        for url in urls[:5]:  # Limiter à 5 URLs
            lignes.append(f"  - {url}")
    
    # Extraire les emails
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texte)
    if emails:
        lignes.append(f"\nEmails trouvés ({len(emails)}):")
        for email in emails[:5]:  # Limiter à 5 emails
            lignes.append(f"  - {email}")
    
    # Extraire les nombres (pourcentages, montants, etc.)
    nombres = re.findall(r'\b\d+[%$€£]?\b', texte)
    if nombres:
        lignes.append(f"\nNombres trouvés ({len(nombres)}):")
        lignes.append(f"  - {', '.join(nombres[:10])}")  # Limiter à 10 nombres
    
    # Extraire les dates (format JJ/MM/AAAA ou YYYY-MM-DD)
    dates = re.findall(r'\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b', texte)
    if dates:
        lignes.append(f"\nDates trouvées ({len(dates)}):")
        lignes.append(f"  - {', '.join(dates[:5])}")  # Limiter à 5 dates
    
    if not any([urls, emails, nombres, dates]):
        lignes.append("\nAucune information clé détectée.")
    
    return "\n".join(lignes)


def synthetiser_resultats(resultats: List[str]) -> str:
    """
    Synthétise plusieurs résultats de recherche en un résumé cohérent.
    
    Args:
        resultats: Liste des résultats à synthétiser
        
    Returns:
        Synthèse des résultats
    """
    if not resultats:
        return "Aucun résultat à synthétiser."
    
    lignes = ["=== SYNTHÈSE DES RÉSULTATS ==="]
    lignes.append(f"Nombre de sources analysées: {len(resultats)}")
    lignes.append("\n--- RÉSUMÉ ---")
    
    # Combiner tous les textes
    texte_complet = " ".join(resultats)
    
    # Extraire les informations clés
    lignes.append(extraire_informations_cles(texte_complet))
    
    # Statistiques basiques
    lignes.append(f"\n--- STATISTIQUES ---")
    lignes.append(f"Longueur totale du texte: {len(texte_complet)} caractères")
    lignes.append(f"Nombre moyen de caractères par source: {len(texte_complet) // len(resultats)}")
    
    return "\n".join(lignes)