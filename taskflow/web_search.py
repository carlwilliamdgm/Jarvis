"""
Module de recherche web avancée pour Jarvis.

Ce module permet à Jarvis d'effectuer des recherches web intelligentes,
similaires aux capacités de Claude dans Chrome, avec analyse et synthèse
des résultats.
"""

import logging
import re
import json
import time
import os
from typing import List, Dict, Optional, Any
from urllib.parse import urlencode, quote_plus, urlparse
import requests

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
        for root in SEARCH_ENGINE_ROOTS:
            if netloc == root or netloc.endswith("." + root):
                if not path or path in ('', 'html', 'l', 'search', 'web'):
                    return True
    except Exception:
        pass
    return False


def is_valid_result(result: Dict[str, Any]) -> bool:
    """Valide qu'un résultat n'est pas un placeholder, une redirection vide ou une racine de moteur."""
    if not isinstance(result, dict):
        return False
    title = (result.get("title") or "").strip().lower()
    url = (result.get("url") or "").strip()
    if not url or is_search_engine_root(url):
        return False
    if title in {"here", "sans titre", "duckduckgo", "google", "bing", "error", "temporairement indisponible"}:
        return False
    if "temporairement indisponible" in title:
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
        4. Wikipedia Search API
        
        Args:
            query: La requête de recherche
            num_results: Nombre de résultats souhaités
            provider: Provider spécifique ('brave', 'duckduckgo_search', 'duckduckgo', 'wikipedia', None pour auto)
            
        Returns:
            Liste de résultats valides avec titre, URL et snippet
        """
        # 1. Provider Brave explicite ou prioritaire
        if (provider == "brave" or (provider is None and self.preferred_provider == "brave")) and self.brave_api_key:
            results = [r for r in self.search_brave(query, num_results) if is_valid_result(r)]
            if results:
                return results

        # 2. ddgs (duckduckgo_search)
        if (provider in (None, "duckduckgo_search", "ddgs")) and DDG_AVAILABLE:
            results = [r for r in self.search_duckduckgo_search(query, num_results) if is_valid_result(r)]
            if results:
                return results

        # 3. DuckDuckGo API classique ou HTML
        if provider in (None, "duckduckgo"):
            results = [r for r in self.search_duckduckgo(query, num_results) if is_valid_result(r)]
            if results:
                return results

        # 4. Fallback Wikipedia (encyclopédique & fiable sans clé API)
        wiki_results = [r for r in self.search_wikipedia(query, min(num_results, 5)) if is_valid_result(r)]
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
        Récupère et extrait le contenu d'une page web.
        
        Args:
            url: URL de la page à récupérer
            max_length: Longueur maximale du contenu à retourner
            
        Returns:
            Dictionnaire avec le titre, le contenu et les métadonnées
        """
        self._rate_limit()
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # Extraction basique du contenu (sans BeautifulSoup pour éviter une dépendance supplémentaire)
            content = response.text
            
            # Extraire le titre
            title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Sans titre"
            
            # Extraire le contenu principal (très basique)
            # Supprimer les scripts, styles et commentaires
            content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            
            # Extraire le texte
            text_content = re.sub(r'<[^>]+>', ' ', content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()
            
            # Limiter la longueur
            if len(text_content) > max_length:
                text_content = text_content[:max_length] + "..."
            
            return {
                "url": url,
                "title": title,
                "content": text_content,
                "status": "success",
                "length": len(text_content)
            }
            
        except requests.RequestException as e:
            return {
                "url": url,
                "error": f"Erreur de récupération: {str(e)}",
                "status": "error"
            }
        except Exception as e:
            return {
                "url": url,
                "error": f"Erreur d'extraction: {str(e)}",
                "status": "error"
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