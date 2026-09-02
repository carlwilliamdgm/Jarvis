# core/llm_client.py

import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from typing import Any, Callable, Dict, List, Optional
import urllib.request

try:
    from groq import Groq as GroqClient
except ImportError:
    GroqClient = None

try:
    import ollama
except ImportError:
    ollama = None

from core.memory import (
    charger_memoire,
    normaliser_memoire,
    sauvegarder_memoire,
)

# Modèles par défaut
MODELE_SOUVERAIN_JARVIS = "jarvis-gc:latest"
MODELES_JARVIS_GC = ["jarvis-gc:latest", "qwen2.5:3b", "qwen2.5:7b"]
MODELES_GROQ = ["openai/gpt-oss-120b"]
MODELES_OPENROUTER = ["meta-llama/llama-3.3-70b-instruct:free"]
MODELE_LOCAL = "qwen2.5:7b"

_EVENT_EMITTER: Optional[Callable[[str, dict], None]] = None


def register_event_emitter(emitter: Callable[[str, dict], None]) -> None:
    """Enregistre un émetteur d'événements global (ex: event_bus.emit)."""
    global _EVENT_EMITTER
    _EVENT_EMITTER = emitter


def _notify_event(event_type: str, data: dict, callback: Optional[Callable[[str, dict], None]] = None) -> None:
    if callback is not None:
        callback(event_type, data)
    elif _EVENT_EMITTER is not None:
        _EVENT_EMITTER(event_type, data)



@dataclass
class LLMMessage:
    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    raw: Optional[Any] = None
    usage: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "message": {"content": self.content},
            "provider": self.provider,
            "model": self.model,
            "raw": self.raw,
        }


@dataclass
class LLMConfig:
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: Optional[float] = None
    extra_options: dict = field(default_factory=dict)


class BaseLLMProvider:
    """Interface abstraite pour tous les fournisseurs de modèles LLM."""

    def __init__(self, nom: str, modeles: list[str], niveau: str = "simple"):
        self.nom = nom
        self.modeles = modeles
        self.niveau = niveau

    def is_available(self) -> bool:
        raise NotImplementedError

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        raise NotImplementedError


class GroqProvider(BaseLLMProvider):
    """Fournisseur Groq avec support multi-clés et bascule automatique sur 429."""

    def __init__(self, modeles: Optional[list[str]] = None):
        super().__init__(
            nom="Groq",
            modeles=modeles or MODELES_GROQ,
            niveau="simple",
        )

    def get_clients(self) -> list:
        if GroqClient is None:
            return []
        clients = []
        i = 1
        while True:
            key = os.environ.get(f"GROQ_API_KEY_{i}")
            if not key:
                break
            clients.append(GroqClient(api_key=key))
            i += 1
        if not clients and os.environ.get("GROQ_API_KEY"):
            clients.append(GroqClient(api_key=os.environ.get("GROQ_API_KEY")))
        return clients

    def is_available(self) -> bool:
        return len(self.get_clients()) > 0

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        cfg = config or LLMConfig()
        clients = self.get_clients()
        if not clients:
            raise RuntimeError("Aucune clé Groq configurée.")

        groq_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
        ]
        derniere_erreur = None

        for client in clients:
            try:
                response = client.chat.completions.create(
                    model=modele,
                    messages=groq_messages,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                )
                contenu = response.choices[0].message.content
                return LLMResponse(
                    content=contenu,
                    provider=self.nom,
                    model=modele,
                    raw=response,
                )
            except Exception as e:
                derniere_erreur = e
                if "429" in str(e):
                    continue
                raise RuntimeError(f"Groq error: {e}") from e

        raise RuntimeError(f"Groq error (toutes clés épuisées): {derniere_erreur}")


class OpenRouterProvider(BaseLLMProvider):
    """Fournisseur OpenRouter avec injection de prompt système et appel HTTP."""

    def __init__(self, modeles: Optional[list[str]] = None):
        super().__init__(
            nom="OpenRouter",
            modeles=modeles or MODELES_OPENROUTER,
            niveau="simple",
        )

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        cfg = config or LLMConfig(max_tokens=2048)
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY absente.")

        systeme = next((m["content"] for m in messages if m["role"] == "system"), "")
        autres = [m for m in messages if m["role"] != "system"]

        messages_envoyes = []
        if systeme:
            messages_envoyes.append({"role": "system", "content": systeme})

        if autres and systeme:
            premier_user = autres[0]["content"]
            autres = list(autres)
            autres[0] = {
                "role": "user",
                "content": f"[INSTRUCTIONS SYSTÈME - À RESPECTER STRICTEMENT]\n{systeme}\n[FIN INSTRUCTIONS]\n\n{premier_user}",
            }

        messages_envoyes.extend([{"role": m["role"], "content": m["content"]} for m in autres])

        payload = json.dumps({
            "model": modele,
            "messages": messages_envoyes,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
        }).encode("utf-8")

        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost/jarvis",
                "X-Title": "Jarvis Local",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            contenu = data["choices"][0]["message"]["content"]
            return LLMResponse(
                content=contenu,
                provider=self.nom,
                model=modele,
                raw=data,
            )
        except Exception as e:
            raise RuntimeError(f"OpenRouter error: {e}") from e


class OllamaProvider(BaseLLMProvider):
    """Fournisseur Ollama local."""

    def __init__(self, modele: str = MODELE_LOCAL):
        super().__init__(
            nom="Ollama",
            modeles=[modele],
            niveau="local",
        )

    def is_available(self) -> bool:
        return ollama is not None

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        if ollama is None:
            raise RuntimeError("Module ollama non disponible.")
        cfg = config or LLMConfig()
        options = {"think": False, "temperature": cfg.temperature}
        options.update(cfg.extra_options)
        try:
            response = ollama.chat(
                model=modele,
                messages=messages,
                options=options,
            )
            # Ollama peut retourner un dict ou un objet
            if isinstance(response, dict):
                content = response.get("message", {}).get("content", "")
            else:
                content = getattr(getattr(response, "message", None), "content", "")
            return LLMResponse(
                content=content,
                provider=self.nom,
                model=modele,
                raw=response,
            )
        except Exception as e:
            raise RuntimeError(f"Ollama non disponible: {e}. Assurez-vous que le service est démarré.") from e


class JarvisGCProvider(BaseLLMProvider):
    """
    Fournisseur souverain The Great Corporation - Modèle local optimisé CPU / AVX2.
    Exploite le modèle propriétaire 'jarvis-gc:latest' avec décodage structuré et gestion éco de la mémoire.
    Comporte une réserve de timeout stricte pour garantir la réactivité instantanée de Jarvis.
    """

    def __init__(self, modeles: Optional[list[str]] = None, host: Optional[str] = None, timeout: float = 45.0):
        super().__init__(
            nom="Jarvis-GC",
            modeles=modeles or MODELES_JARVIS_GC,
            niveau="souverain",
        )
        self.host = host or os.environ.get("JARVIS_MODEL_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        self.default_timeout = float(os.environ.get("JARVIS_GC_TIMEOUT", timeout))

    def is_available(self) -> bool:
        if ollama is None:
            return False
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        if ollama is None:
            raise RuntimeError("Module ollama non disponible pour Jarvis-GC.")

        # Fail-fast : vérification du service avant toute tentative d'inférence.
        # Évite de bloquer 6s sur un timeout réseau si Ollama est éteint.
        if not self.is_available():
            raise RuntimeError(
                f"Service Ollama inaccessible sur {self.host}. "
                "Démarrez Ollama ('ollama serve') puis créez le modèle "
                "('ollama create jarvis-gc -f models/jarvis_gc/Modelfile')."
            )

        cfg = config or LLMConfig(temperature=0.2)
        timeout_val = cfg.timeout or self.default_timeout
        # Sur CPU 8-threads (4 cœurs physiques), utiliser 4 threads physiques
        # garantit que Windows conserve 4 threads libres (zéro freeze système).
        options = {
            "think": False,
            "temperature": cfg.temperature,
            "top_p": 0.9,
            "num_thread": int(os.environ.get("JARVIS_GC_THREADS", 4)),
            "num_ctx": 2048,
        }
        options.update(cfg.extra_options)

        def _do_chat():
            client = ollama.Client(host=self.host) if hasattr(ollama, "Client") else ollama
            kwargs = {
                "model": modele,
                "messages": messages,
                "options": options,
            }
            # Déchargement automatique après 5min d'inactivité
            kwargs["keep_alive"] = "5m"
            return client.chat(**kwargs)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_chat)
                response = future.result(timeout=timeout_val)

            if isinstance(response, dict):
                content = response.get("message", {}).get("content", "")
            else:
                content = getattr(getattr(response, "message", None), "content", "")
            return LLMResponse(
                content=content,
                provider=self.nom,
                model=modele,
                raw=response,
            )
        except concurrent.futures.TimeoutError as e:
            raise TimeoutError(
                f"Délai d'inférence Jarvis-GC dépassé (> {timeout_val}s). "
                f"Envisagez d'utiliser la variante 3B (plus légère) ou "
                f"d'augmenter JARVIS_GC_TIMEOUT dans votre environnement."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Erreur modèle souverain Jarvis-GC ({modele}): {e}") from e


class LLMClient:
    """
    Orchestrateur central des requêtes LLM.
    Gère la cascade de fallback : Souverain Jarvis-GC -> Cloud (Groq/OpenRouter) -> Fallback Local.
    """

    def __init__(
        self,
        cloud_providers: Optional[list[BaseLLMProvider]] = None,
        local_provider: Optional[BaseLLMProvider] = None,
        sovereign_provider: Optional[BaseLLMProvider] = None,
    ):
        self.sovereign_provider = sovereign_provider or JarvisGCProvider()
        self.cloud_providers = cloud_providers or [
            GroqProvider(),
            OpenRouterProvider(),
        ]
        self.local_provider = local_provider or OllamaProvider()

    def get_available_cloud_providers(self) -> list[BaseLLMProvider]:
        return [p for p in self.cloud_providers if p.is_available()]

    def order_cloud_providers(
        self,
        providers: list[BaseLLMProvider],
        memoire: dict,
        complexite: str = "simple",
    ) -> list[BaseLLMProvider]:
        if len(providers) <= 1:
            return providers
        priorite = ["complexe", "simple"] if complexite == "complexe" else ["simple", "complexe"]
        routeur = memoire.get("routeur_modeles", {})
        dernier_global = routeur.get("dernier_provider_cloud")
        ordonnes = []
        for niveau in priorite:
            groupe = [p for p in providers if p.niveau == niveau]
            if not groupe:
                continue
            dernier = routeur.get(f"dernier_provider_{niveau}") or dernier_global
            noms = [p.nom for p in groupe]
            # Priorité absolue au dernier provider valide pour optimiser le temps de réponse
            if dernier in noms:
                idx = noms.index(dernier)
                groupe = [groupe[idx]] + [p for i, p in enumerate(groupe) if i != idx]
            ordonnes.extend(groupe)
        return ordonnes

    def memoriser_provider_cloud(self, nom_provider: str) -> None:
        data = normaliser_memoire(charger_memoire())
        routeur = data.setdefault("routeur_modeles", {})
        routeur["dernier_provider_cloud"] = nom_provider
        for provider in self.get_available_cloud_providers():
            if provider.nom == nom_provider:
                routeur[f"dernier_provider_{provider.niveau}"] = nom_provider
                break
        routeur["maj"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sauvegarder_memoire(data)

    def generate_with_fallback(
        self,
        messages: list[dict],
        memoire: Optional[dict] = None,
        config: Optional[LLMConfig] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
        max_tentatives: int = 2,
    ) -> Optional[dict]:
        """
        Génère une réponse avec cascade de haute performance :
        1. Cloud Ultra-Rapide (Groq / OpenRouter) en Priorité #1 pour réactivité instantanée (< 1s) et intelligence maximale (120B/70B).
        2. Modèle Souverain The Great Corporation (Jarvis-GC) en Fallback Hors-Ligne #1 si le cloud est inaccessible.
        3. Modèle local standard (Ollama fallback) en dernier recours.
        """
        from rich.console import Console
        console = Console()
        cfg = config or LLMConfig()
        mem = memoire or {}

        # 1. CASCADE CLOUD ULTRA-RAPIDE (Priorité #1 - Fast-Track)
        for tentative in range(max_tentatives):
            available_clouds = self.get_available_cloud_providers()
            ordered_clouds = self.order_cloud_providers(available_clouds, mem)

            if ordered_clouds:
                if tentative == 0:
                    console.print("[dim]-> Clé API cloud détectée. Tentative modèles cloud...[/dim]")
                else:
                    console.print(f"[dim yellow]-> Retry modèles cloud (tentative {tentative + 1})...[/dim yellow]")

                for provider in ordered_clouds:
                    nom = provider.nom
                    modele = provider.modeles[0]
                    try:
                        resp = provider.generate(modele, messages, config=cfg)
                        console.print(f"[dim green]✓ {nom} réussi : {modele}[/dim green]")
                        if on_event is not None:
                            on_event("provider", {"provider": nom, "model": modele})
                        self.memoriser_provider_cloud(nom)
                        return resp.to_dict()
                    except Exception as e:
                        console.print(f"[dim yellow]✗ {nom} {modele} indisponible : {str(e)[:100]}[/dim yellow]")
                        continue

            # 2. FALLBACK SOUVERAIN HORS-LIGNE (The Great Corporation Jarvis-GC)
            if self.sovereign_provider and self.sovereign_provider.is_available():
                modele_souverain = self.sovereign_provider.modeles[0]
                try:
                    console.print(f"[dim cyan]-> Mode Hors-Ligne : Modèle Souverain The Great Corporation actif ({modele_souverain})...[/dim cyan]")
                    resp = self.sovereign_provider.generate(modele_souverain, messages, config=cfg)
                    console.print(f"[dim green]✓ {self.sovereign_provider.nom} réussi : {modele_souverain}[/dim green]")
                    if on_event is not None:
                        on_event("provider", {"provider": self.sovereign_provider.nom, "model": modele_souverain})
                    return resp.to_dict()
                except Exception as e:
                    console.print(f"[dim yellow]✗ {self.sovereign_provider.nom} indisponible ({str(e)[:100]}) -> Fallback local standard[/dim yellow]")

            # 3. FALLBACK LOCAL STANDARD
            if tentative == 0:
                console.print(f"[dim]-> Utilisation du modèle local : {MODELE_LOCAL}[/dim]")
            try:
                resp = self.local_provider.generate(MODELE_LOCAL, messages, config=cfg)
                if on_event is not None:
                    on_event("provider", {"provider": self.local_provider.nom, "model": MODELE_LOCAL})
                return resp.to_dict()
            except Exception as e:
                console.print(f"[red]✗ Erreur modèle local : {e}[/red]")
                continue

        return None


# Instance globale singleton
_DEFAULT_CLIENT = LLMClient()


def get_llm_client() -> LLMClient:
    return _DEFAULT_CLIENT


# =============================================================================
# Fonctions et wrappers de compatibilité descendante
# =============================================================================

def modele_souverain_disponible() -> bool:
    """Vérifie si le modèle souverain Jarvis-GC local est actif et disponible."""
    provider = JarvisGCProvider()
    return provider.is_available()


def chat_with_jarvis_gc(modele: str = MODELE_SOUVERAIN_JARVIS, messages: list = None, temperature: float = 0.2) -> dict:
    """Appel direct au modèle souverain Jarvis-GC de The Great Corporation."""
    provider = JarvisGCProvider()
    cfg = LLMConfig(temperature=temperature, extra_options={"json_mode": True})
    resp = provider.generate(modele, messages or [], config=cfg)
    return resp.to_dict()


def get_groq_clients() -> list:
    groq_provider = GroqProvider()
    return groq_provider.get_clients()


def chat_with_cloud(modele: str, messages: list, temperature: float = 0.7) -> dict:
    provider = GroqProvider()
    cfg = LLMConfig(temperature=temperature, max_tokens=1024)
    resp = provider.generate(modele, messages, config=cfg)
    return resp.to_dict()


def chat_with_openrouter(modele: str, messages: list, temperature: float = 0.7) -> dict:
    provider = OpenRouterProvider()
    cfg = LLMConfig(temperature=temperature, max_tokens=2048)
    resp = provider.generate(modele, messages, config=cfg)
    return resp.to_dict()


def chat_with_local(modele: str, messages: list, temperature: float = 0.7) -> dict:
    provider = OllamaProvider(modele=modele)
    cfg = LLMConfig(temperature=temperature)
    resp = provider.generate(modele, messages, config=cfg)
    # Pour compatibilité Ollama directe
    return resp.raw if isinstance(resp.raw, dict) else resp.to_dict()


def providers_cloud_disponibles() -> list[dict]:
    client = get_llm_client()
    disponibles = []
    for p in client.get_available_cloud_providers():
        if isinstance(p, GroqProvider):
            disponibles.append({
                "nom": p.nom,
                "modeles": p.modeles,
                "fonction": chat_with_cloud,
                "niveau": p.niveau,
            })
        elif isinstance(p, OpenRouterProvider):
            disponibles.append({
                "nom": p.nom,
                "modeles": p.modeles,
                "fonction": chat_with_openrouter,
                "niveau": p.niveau,
            })
    return disponibles


def ordonner_providers_cloud(providers: list[dict], memoire: dict, complexite: str = "simple") -> list[dict]:
    if len(providers) <= 1:
        return providers
    priorite = ["complexe", "simple"] if complexite == "complexe" else ["simple", "complexe"]
    routeur = memoire.get("routeur_modeles", {})
    dernier_global = routeur.get("dernier_provider_cloud")
    ordonnes = []
    for niveau in priorite:
        groupe = [p for p in providers if p.get("niveau") == niveau]
        if not groupe:
            continue
        dernier = routeur.get(f"dernier_provider_{niveau}") or dernier_global
        noms = [p["nom"] for p in groupe]
        # Priorité absolue au dernier provider valide pour optimiser le temps de réponse
        if dernier in noms:
            idx = noms.index(dernier)
            groupe = [groupe[idx]] + [p for i, p in enumerate(groupe) if i != idx]
        ordonnes.extend(groupe)
    return ordonnes


def memoriser_provider_cloud(nom_provider: str) -> None:
    _DEFAULT_CLIENT.memoriser_provider_cloud(nom_provider)
