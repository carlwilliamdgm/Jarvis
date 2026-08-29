"""
Module d'automatisation de navigateur pour Jarvis.

Ce module permet à Jarvis de naviguer de manière interactive sur les sites web,
similaire aux capacités de Claude dans Chrome, en utilisant Playwright.

Playwright est choisi pour sa légèreté, sa rapidité et son API moderne.
"""

import asyncio
import base64
import json
from typing import List, Dict, Optional, Any
from enum import Enum


class BrowserType(Enum):
    """Types de navigateurs supportés."""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class BrowserAutomation:
    """Classe principale pour l'automatisation de navigateur."""
    
    def __init__(self, headless: bool = True, browser_type: BrowserType = BrowserType.CHROMIUM):
        """
        Initialise l'automatisation de navigateur.
        
        Args:
            headless: Si True, exécute le navigateur sans interface graphique
            browser_type: Type de navigateur à utiliser
        """
        self.headless = headless
        self.browser_type = browser_type
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
    
    async def __aenter__(self):
        """Initialise le navigateur lors de l'entrée dans le contexte."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Nettoie les ressources lors de la sortie du contexte."""
        await self.close()
    
    async def start(self):
        """Démarre le navigateur et crée une page."""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            
            if self.browser_type == BrowserType.CHROMIUM:
                self.browser = await self.playwright.chromium.launch(headless=self.headless)
            elif self.browser_type == BrowserType.FIREFOX:
                self.browser = await self.playwright.firefox.launch(headless=self.headless)
            elif self.browser_type == BrowserType.WEBKIT:
                self.browser = await self.playwright.webkit.launch(headless=self.headless)
            
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            self.page = await self.context.new_page()
            
        except ImportError:
            raise ImportError(
                "Playwright n'est pas installé. Installez-le avec: "
                "pip install playwright && playwright install"
            )
        except Exception as e:
            raise Exception(f"Erreur lors du démarrage du navigateur: {str(e)}")
    
    async def close(self):
        """Ferme le navigateur et libère les ressources."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass  # Ignorer les erreurs lors du nettoyage
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
    
    async def navigate(self, url: str) -> str:
        """
        Navigue vers une URL spécifique.
        
        Args:
            url: URL vers laquelle naviguer
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré. Appelez start() d'abord.")
        
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return f"Navigation réussie vers {url}"
        except Exception as e:
            return f"Erreur de navigation vers {url}: {str(e)}"
    
    async def click(self, selector: str, timeout: int = 5000) -> str:
        """
        Clique sur un élément de la page.
        
        Args:
            selector: Sélecteur CSS ou XPath de l'élément
            timeout: Timeout en millisecondes
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.click(selector, timeout=timeout)
            return f"Clic réussi sur {selector}"
        except Exception as e:
            return f"Erreur lors du clic sur {selector}: {str(e)}"
    
    async def fill(self, selector: str, value: str, timeout: int = 5000) -> str:
        """
        Remplit un champ de formulaire avec une valeur.
        
        Args:
            selector: Sélecteur CSS ou XPath du champ
            value: Valeur à insérer
            timeout: Timeout en millisecondes
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.fill(selector, value, timeout=timeout)
            return f"Champ {selector} rempli avec succès"
        except Exception as e:
            return f"Erreur lors du remplissage de {selector}: {str(e)}"
    
    async def get_text(self, selector: str = "body") -> str:
        """
        Extrait le texte d'un élément ou de la page entière.
        
        Args:
            selector: Sélecteur CSS ou XPath (défaut: body pour toute la page)
            
        Returns:
            Texte extrait
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            element = await self.page.query_selector(selector)
            if element:
                text = await element.inner_text()
                return text
            else:
                return f"Élément {selector} non trouvé"
        except Exception as e:
            return f"Erreur lors de l'extraction du texte: {str(e)}"
    
    async def get_attribute(self, selector: str, attribute: str) -> str:
        """
        Extrait un attribut spécifique d'un élément.
        
        Args:
            selector: Sélecteur CSS ou XPath de l'élément
            attribute: Nom de l'attribut à extraire
            
        Returns:
            Valeur de l'attribut
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            element = await self.page.query_selector(selector)
            if element:
                value = await element.get_attribute(attribute)
                return value or f"Attribut {attribute} non trouvé"
            else:
                return f"Élément {selector} non trouvé"
        except Exception as e:
            return f"Erreur lors de l'extraction de l'attribut: {str(e)}"
    
    async def wait_for_element(self, selector: str, timeout: int = 10000) -> str:
        """
        Attend qu'un élément apparaisse sur la page.
        
        Args:
            selector: Sélecteur CSS ou XPath de l'élément
            timeout: Timeout en millisecondes
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return f"Élément {selector} trouvé"
        except Exception as e:
            return f"Timeout: Élément {selector} non trouvé après {timeout}ms"
    
    async def screenshot(self, path: Optional[str] = None, full_page: bool = False) -> str:
        """
        Prend une capture d'écran de la page.
        
        Args:
            path: Chemin où sauvegarder la capture (optionnel)
            full_page: Si True, capture toute la page (scrolling inclus)
            
        Returns:
            Message de confirmation ou base64 de l'image si pas de chemin
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            if path:
                await self.page.screenshot(path=path, full_page=full_page)
                return f"Capture d'écran sauvegardée dans {path}"
            else:
                screenshot = await self.page.screenshot(full_page=full_page)
                # Retourner en base64 pour utilisation dans l'interface
                return f"data:image/png;base64,{base64.b64encode(screenshot).decode()}"
        except Exception as e:
            return f"Erreur lors de la capture d'écran: {str(e)}"
    
    async def scroll(self, pixels: int = 500) -> str:
        """
        Scrolle la page verticalement.
        
        Args:
            pixels: Nombre de pixels à scroller (positif = bas, négatif = haut)
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.evaluate(f"window.scrollBy(0, {pixels})")
            return f"Scroll de {pixels} pixels effectué"
        except Exception as e:
            return f"Erreur lors du scroll: {str(e)}"
    
    async def execute_javascript(self, script: str) -> str:
        """
        Exécute du JavaScript dans la page.
        
        Args:
            script: Code JavaScript à exécuter
            
        Returns:
            Résultat de l'exécution
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            result = await self.page.evaluate(script)
            return f"Résultat: {json.dumps(result, default=str)}"
        except Exception as e:
            return f"Erreur lors de l'exécution JavaScript: {str(e)}"
    
    async def get_url(self) -> str:
        """
        Retourne l'URL actuelle de la page.
        
        Returns:
            URL actuelle
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            return self.page.url
        except Exception as e:
            return f"Erreur lors de la récupération de l'URL: {str(e)}"
    
    async def get_title(self) -> str:
        """
        Retourne le titre de la page.
        
        Returns:
            Titre de la page
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            return await self.page.title()
        except Exception as e:
            return f"Erreur lors de la récupération du titre: {str(e)}"
    
    async def wait_for_navigation(self, timeout: int = 30000) -> str:
        """
        Attend qu'une navigation se produise.
        
        Args:
            timeout: Timeout en millisecondes
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
            return "Navigation terminée"
        except Exception as e:
            return f"Erreur ou timeout lors de l'attente de navigation: {str(e)}"
    
    async def select_option(self, selector: str, value: str) -> str:
        """
        Sélectionne une option dans un élément <select>.
        
        Args:
            selector: Sélecteur CSS ou XPath de l'élément select
            value: Valeur de l'option à sélectionner
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.select_option(selector, value)
            return f"Option {value} sélectionnée dans {selector}"
        except Exception as e:
            return f"Erreur lors de la sélection: {str(e)}"
    
    async def check(self, selector: str) -> str:
        """
        Coche une case à cocher (checkbox).
        
        Args:
            selector: Sélecteur CSS ou XPath de la checkbox
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.check(selector)
            return f"Checkbox {selector} cochée"
        except Exception as e:
            return f"Erreur lors du cochage: {str(e)}"
    
    async def uncheck(self, selector: str) -> str:
        """
        Décoche une case à cocher (checkbox).
        
        Args:
            selector: Sélecteur CSS ou XPath de la checkbox
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.uncheck(selector)
            return f"Checkbox {selector} décochée"
        except Exception as e:
            return f"Erreur lors du décochage: {str(e)}"
    
    async def hover(self, selector: str) -> str:
        """
        Survole un élément avec la souris.
        
        Args:
            selector: Sélecteur CSS ou XPath de l'élément
            
        Returns:
            Message de confirmation
        """
        if not self.page:
            raise RuntimeError("Le navigateur n'est pas démarré.")
        
        try:
            await self.page.hover(selector)
            return f"Survol de {selector} effectué"
        except Exception as e:
            return f"Erreur lors du survol: {str(e)}"


# Fonctions synchrones unifiées pour l'intégration avec Jarvis (session persistante)

def _get_persistent_session(headless: bool = True):
    """Récupère la session de navigation persistante par défaut."""
    from core.browser_session import get_session_manager
    return get_session_manager().get_default_session(headless=headless)


def naviguer_vers(url: str, headless: bool = True) -> str:
    """
    Fonction synchrone pour naviguer vers une URL sur la session persistante.
    
    Args:
        url: URL vers laquelle naviguer
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat de la navigation
    """
    session = _get_persistent_session(headless=headless)
    return session.navigate_sync(url)


def cliquer_element(selector: str, url: str = None, headless: bool = True) -> str:
    """
    Fonction synchrone pour cliquer sur un élément.
    
    Args:
        selector: Sélecteur CSS ou XPath de l'élément
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat du clic
    """
    session = _get_persistent_session(headless=headless)
    if url:
        current_url = session.get_url_sync()
        if current_url != url:
            session.navigate_sync(url)
    return session.click_sync(selector)


def remplir_formulaire(selector: str, valeur: str, url: str = None, headless: bool = True) -> str:
    """
    Fonction synchrone pour remplir un champ de formulaire.
    
    Args:
        selector: Sélecteur CSS ou XPath du champ
        valeur: Valeur à insérer
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat du remplissage
    """
    session = _get_persistent_session(headless=headless)
    if url:
        current_url = session.get_url_sync()
        if current_url != url:
            session.navigate_sync(url)
    return session.fill_sync(selector, valeur)


def extraire_texte(selector: str = "body", url: str = None, headless: bool = True) -> str:
    """
    Fonction synchrone pour extraire du texte.
    
    Args:
        selector: Sélecteur CSS ou XPath (défaut: body)
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Texte extrait
    """
    session = _get_persistent_session(headless=headless)
    if url:
        current_url = session.get_url_sync()
        if current_url != url:
            session.navigate_sync(url)
    return session.get_text_sync(selector)


def prendre_capture(path: str = None, url: str = None, full_page: bool = False, headless: bool = True) -> str:
    """
    Fonction synchrone pour prendre une capture d'écran.
    
    Args:
        path: Chemin où sauvegarder (optionnel)
        url: URL optionnelle où naviguer d'abord
        full_page: Si True, capture toute la page
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat de la capture
    """
    session = _get_persistent_session(headless=headless)
    if url:
        current_url = session.get_url_sync()
        if current_url != url:
            session.navigate_sync(url)
    return session.screenshot_sync(path=path, full_page=full_page)


def executer_sequence(actions: List[Dict[str, Any]], headless: bool = True) -> str:
    """
    Exécute une séquence d'actions de navigation sur la session persistante.
    
    Args:
        actions: Liste d'actions à exécuter
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultats de toutes les actions
    """
    session = _get_persistent_session(headless=headless)
    results = []
    
    for action in actions:
        action_type = action.get("type")
        
        if action_type == "navigate":
            result = session.navigate_sync(action["url"])
        elif action_type == "click":
            result = session.click_sync(action["selector"])
        elif action_type == "fill":
            result = session.fill_sync(action["selector"], action["value"])
        elif action_type == "wait":
            result = session.wait_for_element_sync(action["selector"])
        elif action_type == "screenshot":
            result = session.screenshot_sync(action.get("path"), action.get("full_page", False))
        elif action_type == "scroll":
            result = session.scroll_sync(action.get("pixels", 500))
        elif action_type == "javascript":
            result = session.execute_javascript_sync(action["script"])
        elif action_type == "select":
            result = session.select_option_sync(action["selector"], action["value"])
        elif action_type == "check":
            result = session.check_sync(action["selector"])
        elif action_type == "uncheck":
            result = session.uncheck_sync(action["selector"])
        elif action_type == "hover":
            result = session.hover_sync(action["selector"])
        else:
            result = f"Action inconnue: {action_type}"
        
        results.append(f"{action_type}: {result}")
    
    return "\n".join(results)


def obtenir_infos_page(url: str = None, headless: bool = True) -> str:
    """
    Obtient des informations détaillées sur la page actuelle.
    
    Args:
        url: URL optionnelle où naviguer
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Informations sur la page
    """
    session = _get_persistent_session(headless=headless)
    if url:
        current_url = session.get_url_sync()
        if current_url != url:
            session.navigate_sync(url)
    
    return session.get_info_sync()


def fermer_navigateur() -> str:
    """
    Ferme la session de navigation persistante et libère les ressources.
    
    Returns:
        Confirmation de fermeture
    """
    from core.browser_session import get_session_manager
    get_session_manager().close_default_session()
    return "Navigateur fermé avec succès"


def reinitialiser_navigateur() -> str:
    """
    Réinitialise la session de navigation persistante.
    
    Returns:
        Confirmation de réinitialisation
    """
    fermer_navigateur()
    return "Session de navigation réinitialisée"