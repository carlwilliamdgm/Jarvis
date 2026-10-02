"""
BrowserAgent — Agent de navigation autonome pour Jarvis.

Ce module implémente la boucle ReAct (Observe → Decide → Act) qui permet
à Jarvis d'accomplir des tâches complexes sur le web de manière autonome,
à la façon de Claude dans Chrome.

**Principe de souveraineté :**
    - TaskFlow (ce module) : OBSERVE (DOM snapshot) et EXÉCUTE (Playwright).
      Il ne raisonne pas, ne prend pas de décisions autonomes.
    - Core Intellect (core_intellect.intellect) : DÉCIDE de la prochaine
      action via ``planifier_etape_navigation()``. C'est le seul module qui pense.

Architecture :
    - ``_take_snapshot()``          : extrait et indexe les éléments cliquables
    - ``BrowserAgent._decide()``    : délègue à Core Intellect (planifier_etape_navigation)
    - ``BrowserAgent._execute_action()`` : exécute la décision via Playwright
    - ``BrowserAgent.accomplir()``  : orchestre la boucle ReAct
    - ``_fermer_popups_cookies()``  : détection et fermeture automatique des modales RGPD
    - Tout contenu retourné est marqué origin=RequestOrigin.EXTERNAL (DataShield)
"""


from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from greatos_contracts import RequestOrigin

logger = logging.getLogger(__name__)

# ─── Sélecteurs RGPD connus ────────────────────────────────────────────────────
_COOKIE_BUTTON_TEXTS = [
    "accepter", "accept", "j'accepte", "i accept", "tout accepter",
    "accept all", "accepter tout", "agree", "ok", "je comprends",
    "fermer", "close", "dismiss", "got it", "compris",
    "continuer sans accepter", "refuser", "reject all",
]

_COOKIE_SELECTORS = [
    # Attributs aria courants
    "[aria-label*='cookie' i]",
    "[aria-label*='consent' i]",
    "[class*='cookie' i] button",
    "[class*='consent' i] button",
    "[id*='cookie' i] button",
    "[id*='gdpr' i] button",
    "[id*='consent' i] button",
    # Frameworks courants
    ".fc-button-label",          # Fides / Sourcepoint
    "#onetrust-accept-btn-handler",
    ".onetrust-accept-btn-handler",
    "[data-testid*='accept' i]",
    "[data-cy*='accept' i]",
    ".cc-btn.cc-allow",          # cookieconsent
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
]

# ─── Types de résultats ─────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """Résultat d'une étape de navigation."""
    action: str
    success: bool
    observation: str
    url: str = ""
    error: str = ""


@dataclass
class AgentResult:
    """Résultat final d'une tâche de navigation."""
    success: bool
    objectif: str
    reponse: str
    url_finale: str
    steps: list[StepResult] = field(default_factory=list)
    contenu_extrait: str = ""
    origin: RequestOrigin = RequestOrigin.EXTERNAL
    erreur: str = ""


# ─── Extraction du DOM interactif ──────────────────────────────────────────────

# JavaScript injecté dans la page pour extraire les éléments interactifs
_JS_DOM_SNAPSHOT = r"""
(function() {
    const MAX_ELEMENTS = 60;
    const elements = [];
    let idx = 1;

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function label(el) {
        return (
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            el.getAttribute('name') ||
            el.getAttribute('alt') ||
            el.innerText?.trim().substring(0, 80) ||
            el.getAttribute('value') ||
            el.getAttribute('href') ||
            ''
        ).replace(/\s+/g, ' ').trim();
    }

    // Liens
    document.querySelectorAll('a[href]').forEach(el => {
        if (idx > MAX_ELEMENTS) return;
        if (!visible(el)) return;
        const lbl = label(el);
        if (!lbl) return;
        elements.push({idx: idx++, type: 'link', label: lbl, href: el.href || ''});
    });

    // Boutons
    document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(el => {
        if (idx > MAX_ELEMENTS) return;
        if (!visible(el)) return;
        const lbl = label(el);
        if (!lbl) return;
        elements.push({idx: idx++, type: 'button', label: lbl});
    });

    // Champs de saisie
    document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select').forEach(el => {
        if (idx > MAX_ELEMENTS) return;
        if (!visible(el)) return;
        const lbl = label(el);
        elements.push({idx: idx++, type: el.tagName.toLowerCase() === 'select' ? 'select' : 'input', label: lbl || '(champ sans nom)', inputType: el.type || ''});
    });

    return {
        url: window.location.href,
        title: document.title,
        elements: elements
    };
})();
"""

_JS_CLICK_BY_INDEX = r"""
(function(targetIdx) {
    const elements = [];
    let idx = 1;

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function collect(selector) {
        document.querySelectorAll(selector).forEach(el => {
            if (visible(el)) elements.push({el, idx: idx++});
        });
    }

    collect('a[href]');
    collect('button, input[type="submit"], input[type="button"]');
    collect('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');

    const target = elements.find(e => e.idx === targetIdx);
    if (target) {
        target.el.scrollIntoView({block: 'center', behavior: 'smooth'});
        target.el.click();
        return 'clicked';
    }
    return 'not_found';
})(arguments[0]);
"""

_JS_TYPE_BY_INDEX = r"""
(function(targetIdx, value) {
    const elements = [];
    let idx = 1;

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function collect(selector) {
        document.querySelectorAll(selector).forEach(el => {
            if (visible(el)) elements.push({el, idx: idx++});
        });
    }

    collect('a[href]');
    collect('button, input[type="submit"], input[type="button"]');
    collect('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');

    const target = elements.find(e => e.idx === targetIdx);
    if (target && (target.el.tagName === 'INPUT' || target.el.tagName === 'TEXTAREA' || target.el.tagName === 'SELECT')) {
        target.el.focus();
        target.el.value = '';
        // Déclencher les événements pour les frameworks réactifs (React, Vue, Angular)
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
        if (nativeInputValueSetter) nativeInputValueSetter.set.call(target.el, value);
        target.el.dispatchEvent(new Event('input', {bubbles: true}));
        target.el.dispatchEvent(new Event('change', {bubbles: true}));
        return 'typed';
    }
    return 'not_found';
})(arguments[0], arguments[1]);
"""


def _parse_snapshot(raw: Any) -> tuple[str, str, list[dict]]:
    """Parse le résultat brut du snapshot JS en (url, title, elements)."""
    if not isinstance(raw, dict):
        return "", "", []
    return (
        raw.get("url", ""),
        raw.get("title", ""),
        raw.get("elements", []),
    )


def _format_snapshot(url: str, title: str, elements: list[dict]) -> str:
    """Formate le snapshot en texte lisible par le LLM."""
    lines = [
        f"URL: {url}",
        f"Titre: {title}",
        "",
        "Éléments interactifs disponibles:",
    ]
    for el in elements:
        t = el.get("type", "?")
        lbl = el.get("label", "")
        i = el.get("idx", "?")
        if t == "link":
            href = el.get("href", "")
            lines.append(f"  [{i}] LIEN: {lbl}  →  {href[:80]}")
        elif t == "button":
            lines.append(f"  [{i}] BOUTON: {lbl}")
        elif t == "input":
            it = el.get("inputType", "text")
            lines.append(f"  [{i}] CHAMP ({it}): {lbl}")
        elif t == "select":
            lines.append(f"  [{i}] LISTE: {lbl}")
        elif t == "textarea":
            lines.append(f"  [{i}] TEXTAREA: {lbl}")
    return "\n".join(lines)


# ─── BrowserAgent ──────────────────────────────────────────────────────────────

class BrowserAgent:
    """
    Agent de navigation autonome à boucle ReAct.

    Il s'appuie sur la session Playwright de Jarvis (BrowserSession) et
    utilise le LLM via Core Intellect pour décider des actions à chaque étape.

    Usage:
        agent = BrowserAgent()
        result = agent.accomplir("Cherche le prix Paris-Montréal le 15 oct sur Google Flights")
    """

    MAX_STEPS = 15
    _THINK_TIMEOUT = 30.0   # secondes accordées au LLM pour décider

    def __init__(
        self,
        headless: bool = True,
        on_step: Callable[[StepResult], None] | None = None,
    ):
        self.headless = headless
        self.on_step = on_step  # callback optionnel pour suivre la progression

    # ── API publique ────────────────────────────────────────────────────────────

    def accomplir(
        self,
        objectif: str,
        url_depart: str = "",
    ) -> AgentResult:
        """
        Accomplit une tâche web de manière autonome.

        Args:
            objectif: Description en langage naturel de la tâche (ex: "Cherche le prix du vol Paris-Montréal").
            url_depart: URL où commencer. Si vide, l'agent démarre sur Google.

        Returns:
            AgentResult avec le résultat de la tâche et le contenu extrait.
        """
        from taskflow.browser_session import get_session_manager

        try:
            session = get_session_manager().get_default_session(headless=self.headless)
        except Exception as e:
            return AgentResult(
                success=False,
                objectif=objectif,
                reponse="",
                url_finale="",
                erreur=f"Impossible de démarrer le navigateur: {e}",
            )

        # URL de départ — si non spécifiée, recherche Google directe
        start_url = url_depart or f"https://www.google.com/search?q={_urlencode_simple(objectif)}&hl=fr"

        try:
            nav = session.navigate_sync(start_url, timeout=40.0)
            logger.debug("Navigation initiale: %s", nav)
        except Exception as e:
            return AgentResult(
                success=False,
                objectif=objectif,
                reponse="",
                url_finale=start_url,
                erreur=f"Échec navigation initiale: {e}",
            )

        # Fermer les pop-ups RGPD immédiatement
        self._fermer_popups_cookies(session)

        steps: list[StepResult] = []
        contenu_accumule: list[str] = []

        for step_num in range(self.MAX_STEPS):
            # ── 1. Observe ──────────────────────────────────────────────────
            snapshot_raw = self._take_snapshot(session)
            if snapshot_raw is None:
                break

            url_courante, title, elements = _parse_snapshot(snapshot_raw)
            snapshot_text = _format_snapshot(url_courante, title, elements)

            # ── 2. Decide ───────────────────────────────────────────────────
            decision = self._decide(
                objectif=objectif,
                snapshot=snapshot_text,
                steps_history=steps,
                step_num=step_num,
            )

            if decision is None:
                logger.warning("BrowserAgent: décision LLM invalide à l'étape %d", step_num)
                break

            action = decision.get("action", "")
            params = decision.get("params", {})
            raisonnement = decision.get("raisonnement", "")
            termine = decision.get("termine", False)
            reponse_finale = decision.get("reponse_finale", "")

            logger.debug("BrowserAgent step %d: action=%s, params=%s", step_num, action, params)

            # ── 3. Act ──────────────────────────────────────────────────────
            step_result = self._execute_action(
                session=session,
                action=action,
                params=params,
                url_courante=url_courante,
            )
            step_result.observation = f"{raisonnement} → {step_result.observation}"
            steps.append(step_result)

            # Accumuler le contenu extrait si l'action a retourné du texte utile
            if action == "extraire_contenu" and step_result.success:
                contenu_accumule.append(step_result.observation)

            # Callback de progression
            if self.on_step:
                try:
                    self.on_step(step_result)
                except Exception:
                    pass

            # Fermer les éventuels pop-ups apparus après l'action
            self._fermer_popups_cookies(session)

            if termine:
                url_finale = session.get_url_sync() if session.is_alive() else url_courante
                # Extraire le contenu final si pas déjà fait
                if not contenu_accumule:
                    contenu_accumule.append(self._extraire_texte_propre(session))

                return AgentResult(
                    success=True,
                    objectif=objectif,
                    reponse=reponse_finale,
                    url_finale=url_finale,
                    steps=steps,
                    contenu_extrait="\n\n".join(contenu_accumule),
                    origin=RequestOrigin.EXTERNAL,
                )

            # Pause légère pour laisser les requêtes réseau se terminer
            time.sleep(0.5)

        # Boucle épuisée sans succès : retourner ce qu'on a
        url_finale = ""
        try:
            url_finale = session.get_url_sync()
        except Exception:
            pass

        return AgentResult(
            success=False,
            objectif=objectif,
            reponse="",
            url_finale=url_finale,
            steps=steps,
            contenu_extrait="\n\n".join(contenu_accumule),
            origin=RequestOrigin.EXTERNAL,
            erreur=f"Limite de {self.MAX_STEPS} étapes atteinte sans résoudre la tâche.",
        )

    # ── Prise de snapshot ──────────────────────────────────────────────────────

    def _take_snapshot(self, session) -> dict | None:
        """Exécute le JS de snapshot dans la page et retourne le dict brut."""
        try:
            raw_str = session.execute_javascript_sync(_JS_DOM_SNAPSHOT, timeout=15.0)
            # execute_javascript_sync retourne "Résultat: {...}"
            if isinstance(raw_str, str) and raw_str.startswith("Résultat: "):
                raw_str = raw_str[len("Résultat: "):]
            import ast
            try:
                return json.loads(raw_str)
            except (json.JSONDecodeError, TypeError):
                try:
                    return ast.literal_eval(raw_str)
                except Exception:
                    return None
        except Exception as e:
            logger.warning("BrowserAgent: snapshot échoué: %s", e)
            return None

    # ── Décision LLM ───────────────────────────────────────────────────────────

    def _decide(
        self,
        objectif: str,
        snapshot: str,
        steps_history: list[StepResult],
        step_num: int,
    ) -> dict | None:
        """
        Délègue la décision de navigation à Core Intellect.

        **Principe de souveraineté :** TaskFlow ne raisonne pas. Il observe (snapshot DOM)
        et exécute (Playwright). C'est Core Intellect qui décide de la prochaine action.

        Collaboration :
            TaskFlow → fournit l'observation (snapshot, historique, objectif)
            Core Intellect → retourne la décision (action, params, raisonnement)
            TaskFlow → exécute la décision via Playwright

        Returns:
            Dict avec les clés : action, params, raisonnement, termine, reponse_finale.
            None si Core Intellect est indisponible.
        """
        # Convertir les StepResult en dicts légers pour Core Intellect
        historique_dicts = [
            {
                "action": s.action,
                "observation": s.observation[:150],
                "success": s.success,
            }
            for s in steps_history
        ]

        from core_intellect.intellect import planifier_etape_navigation
        return planifier_etape_navigation(
            objectif=objectif,
            snapshot=snapshot,
            historique_etapes=historique_dicts,
            step_num=step_num,
        )



    # ── Exécution d'action ─────────────────────────────────────────────────────

    def _execute_action(
        self,
        session,
        action: str,
        params: dict,
        url_courante: str,
    ) -> StepResult:
        """Dispatch vers le handler d'action approprié."""
        try:
            if action == "navigate":
                return self._act_navigate(session, params, url_courante)
            elif action == "click":
                return self._act_click(session, params, url_courante)
            elif action == "type":
                return self._act_type(session, params, url_courante)
            elif action == "scroll":
                return self._act_scroll(session, params, url_courante)
            elif action == "wait":
                return self._act_wait(params, url_courante)
            elif action == "extraire_contenu":
                return self._act_extract(session, url_courante)
            elif action == "terminer":
                return StepResult(
                    action="terminer",
                    success=True,
                    observation="Tâche terminée.",
                    url=url_courante,
                )
            else:
                return StepResult(
                    action=action,
                    success=False,
                    observation=f"Action inconnue: {action}",
                    url=url_courante,
                )
        except Exception as e:
            return StepResult(
                action=action,
                success=False,
                observation=f"Erreur inattendue: {e}",
                url=url_courante,
                error=str(e),
            )

    def _act_navigate(self, session, params: dict, url_courante: str) -> StepResult:
        url = params.get("url", "")
        if not url:
            return StepResult("navigate", False, "URL manquante", url_courante)
        # Ajouter le schéma si manquant
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            result = session.navigate_sync(url, timeout=40.0)
            success = "réussie" in result.lower() or "navigation" in result.lower()
            new_url = session.get_url_sync()
            return StepResult("navigate", success, result[:200], new_url)
        except Exception as e:
            return StepResult("navigate", False, str(e), url_courante, str(e))

    def _act_click(self, session, params: dict, url_courante: str) -> StepResult:
        index = params.get("index")
        if index is None:
            return StepResult("click", False, "Index manquant", url_courante)
        try:
            raw = session.execute_javascript_sync(
                f"({_JS_CLICK_BY_INDEX.replace('arguments[0]', str(index))})()",
                timeout=10.0,
            )
            # Attendre que la page se charge éventuellement
            time.sleep(1.0)
            new_url = session.get_url_sync()
            if "clicked" in str(raw):
                return StepResult("click", True, f"Clic sur élément [{index}] réussi", new_url)
            else:
                return StepResult("click", False, f"Élément [{index}] non trouvé", url_courante)
        except Exception as e:
            return StepResult("click", False, str(e), url_courante, str(e))

    def _act_type(self, session, params: dict, url_courante: str) -> StepResult:
        index = params.get("index")
        value = params.get("value", "")
        if index is None or not value:
            return StepResult("type", False, "Index ou valeur manquant", url_courante)
        try:
            js = (
                f"(function(targetIdx, value) {{"
                f"{_JS_TYPE_BY_INDEX.split('(function(targetIdx, value) {{')[1].rsplit('(arguments[0], arguments[1]);')[0]}"
                f"}}({index}, {json.dumps(value)}))"
            )
            raw = session.execute_javascript_sync(js, timeout=10.0)
            if "typed" in str(raw):
                return StepResult("type", True, f"Saisie '{value[:40]}' dans [{index}]", url_courante)
            else:
                return StepResult("type", False, f"Champ [{index}] non trouvé ou non éditable", url_courante)
        except Exception as e:
            return StepResult("type", False, str(e), url_courante, str(e))

    def _act_scroll(self, session, params: dict, url_courante: str) -> StepResult:
        pixels = int(params.get("pixels", 500))
        try:
            session.scroll_sync(pixels, timeout=5.0)
            return StepResult("scroll", True, f"Scroll de {pixels}px effectué", url_courante)
        except Exception as e:
            return StepResult("scroll", False, str(e), url_courante, str(e))

    def _act_wait(self, params: dict, url_courante: str) -> StepResult:
        seconds = min(float(params.get("seconds", 2.0)), 5.0)
        time.sleep(seconds)
        return StepResult("wait", True, f"Attente de {seconds}s", url_courante)

    def _act_extract(self, session, url_courante: str) -> StepResult:
        try:
            texte = self._extraire_texte_propre(session)
            return StepResult(
                "extraire_contenu",
                True,
                f"[SOURCE EXTERNE NON VÉRIFIÉE] {texte[:3000]}",
                url_courante,
            )
        except Exception as e:
            return StepResult("extraire_contenu", False, str(e), url_courante, str(e))

    # ── Extraction de texte propre ─────────────────────────────────────────────

    def _extraire_texte_propre(self, session) -> str:
        """
        Extrait le texte visible de la page en éliminant nav/header/footer/aside.
        Marqué automatiquement comme source externe.
        """
        _js_extract = r"""
(function() {
    // Supprimer les éléments de bruit
    const noiseSelectors = ['nav', 'header', 'footer', 'aside', '.cookie-banner',
        '[class*="cookie"]', '[class*="gdpr"]', '[class*="popup"]',
        '[class*="modal"]', '[class*="overlay"]', '[role="banner"]',
        '[role="navigation"]', '[role="contentinfo"]'];

    noiseSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => el.remove && el.remove());
    });

    const body = document.body;
    if (!body) return '';

    // Prioriser main/article si disponibles
    const main = body.querySelector('main, article, [role="main"]');
    const src = main || body;

    const text = src.innerText || src.textContent || '';
    return text.replace(/\s+/g, ' ').replace(/\n{3,}/g, '\n\n').trim().substring(0, 8000);
})();
"""
        try:
            raw = session.execute_javascript_sync(_js_extract, timeout=15.0)
            if isinstance(raw, str) and raw.startswith("Résultat: "):
                raw = raw[len("Résultat: "):]
            # Décoder les entités JSON string si nécessaire
            try:
                texte = json.loads(raw) if raw.startswith('"') else raw
            except Exception:
                texte = raw
            return str(texte).strip()
        except Exception as e:
            logger.warning("BrowserAgent: extraction texte échouée: %s", e)
            return ""

    # ── Fermeture des pop-ups RGPD ─────────────────────────────────────────────

    def _fermer_popups_cookies(self, session) -> bool:
        """
        Tente de fermer les bannières RGPD / pop-ups cookies.
        Retourne True si une bannière a été fermée.
        """
        # Stratégie 1 : sélecteurs CSS connus
        for selector in _COOKIE_SELECTORS:
            try:
                js = f"var el = document.querySelector({json.dumps(selector)}); if (el) {{ el.click(); true; }} else false;"
                raw = session.execute_javascript_sync(js, timeout=5.0)
                if "true" in str(raw).lower():
                    time.sleep(0.5)
                    return True
            except Exception:
                pass

        # Stratégie 2 : texte des boutons
        for text in _COOKIE_BUTTON_TEXTS:
            try:
                js = f"""
(function() {{
    var buttons = document.querySelectorAll('button, a[role="button"], input[type="button"], input[type="submit"]');
    for (var b of buttons) {{
        if ((b.innerText || b.value || '').toLowerCase().includes({json.dumps(text)})) {{
            b.click();
            return true;
        }}
    }}
    return false;
}})();
"""
                raw = session.execute_javascript_sync(js, timeout=5.0)
                if "true" in str(raw).lower():
                    time.sleep(0.5)
                    return True
            except Exception:
                pass

        return False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _urlencode_simple(text: str) -> str:
    """Encode une chaîne pour utilisation dans une URL."""
    from urllib.parse import quote_plus
    return quote_plus(text)


# ─── API publique (wrapper synchrone) ─────────────────────────────────────────

def accomplir_tache_web(
    objectif: str,
    url_depart: str = "",
    headless: bool = True,
) -> str:
    """
    Accomplit une tâche web de manière autonome et retourne une réponse en langage naturel.

    Cette fonction est le point d'entrée enregistré dans OUTILS sous le nom
    ``accomplir_tache_web``. Elle encapsule BrowserAgent et formate le résultat.

    Args:
        objectif: La tâche à accomplir (ex: "Cherche le prix du vol Paris-Montréal le 15 oct").
        url_depart: URL de départ optionnelle. Si vide, démarre sur Google.
        headless: Si False, ouvre le navigateur en mode visible (débogage).

    Returns:
        Réponse formatée avec le résultat ou un message d'erreur explicite.
    """
    agent = BrowserAgent(headless=headless)

    try:
        result = agent.accomplir(objectif=objectif, url_depart=url_depart)
    except Exception as e:
        return f"❌ Erreur critique du BrowserAgent: {e}"

    if result.success:
        lignes = [
            f"✅ Tâche accomplie : {result.objectif}",
            f"   URL finale : {result.url_finale}",
            f"   Étapes : {len(result.steps)}",
            "",
        ]
        if result.reponse:
            lignes.append(result.reponse)
        if result.contenu_extrait and not result.reponse:
            lignes.append("--- Contenu extrait ---")
            lignes.append(result.contenu_extrait[:3000])
        return "\n".join(lignes)
    else:
        lignes = [
            f"⚠️ Tâche non résolue : {result.objectif}",
            f"   Raison : {result.erreur or 'Limite d étapes atteinte'}",
            f"   URL dernière : {result.url_finale}",
            f"   Étapes exécutées : {len(result.steps)}",
        ]
        if result.contenu_extrait:
            lignes.append("\n--- Contenu partiel extrait ---")
            lignes.append(result.contenu_extrait[:2000])
        return "\n".join(lignes)
