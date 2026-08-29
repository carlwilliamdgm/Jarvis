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


class LLMClient:
    """
    Orchestrateur central des requêtes LLM.
    Gère la cascade de fallback (Cloud -> Local), l'ordonnancement et les notifications d'événements.
    """

    def __init__(
        self,
        cloud_providers: Optional[list[BaseLLMProvider]] = None,
        local_provider: Optional[BaseLLMProvider] = None,
    ):
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
        ordonnes = []
        for niveau in priorite:
            groupe = [p for p in providers if p.niveau == niveau]
            if not groupe:
                continue
            dernier = routeur.get(f"dernier_provider_{niveau}")
            noms = [p.nom for p in groupe]
            if dernier in noms:
                index_suivant = (noms.index(dernier) + 1) % len(groupe)
                groupe = groupe[index_suivant:] + groupe[:index_suivant]
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
        Génère une réponse en essayant les providers cloud disponibles puis retombe sur Ollama local.
        Retourne un dictionnaire compatible avec le format existant {'message': {'content': ...}}
        """
        from rich.console import Console
        console = Console()
        cfg = config or LLMConfig()
        mem = memoire or {}

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

            # Fallback local
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
    ordonnes = []
    for niveau in priorite:
        groupe = [p for p in providers if p.get("niveau") == niveau]
        if not groupe:
            continue
        dernier = routeur.get(f"dernier_provider_{niveau}")
        noms = [p["nom"] for p in groupe]
        if dernier in noms:
            index_suivant = (noms.index(dernier) + 1) % len(groupe)
            groupe = groupe[index_suivant:] + groupe[:index_suivant]
        ordonnes.extend(groupe)
    return ordonnes


def memoriser_provider_cloud(nom_provider: str) -> None:
    _DEFAULT_CLIENT.memoriser_provider_cloud(nom_provider)
