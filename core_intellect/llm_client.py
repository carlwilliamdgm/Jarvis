# core_intellect/llm_client.py

import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import threading
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

from context_engine.memory import (
    charger_memoire,
    normaliser_memoire,
    sauvegarder_memoire,
)


def _extraire_texte_message_llm(msg) -> str:
    """Récupère le texte utile d'un message provider, y compris les champs reasoning."""
    contenu = getattr(msg, "content", None)
    if isinstance(contenu, str) and contenu.strip():
        return contenu
    if isinstance(contenu, list):
        fragments = []
        for part in contenu:
            if isinstance(part, str):
                fragments.append(part)
            elif isinstance(part, dict):
                fragments.append(str(part.get("text") or part.get("content") or ""))
            else:
                fragments.append(str(getattr(part, "text", "") or ""))
        joint = "".join(fragments)
        if joint.strip():
            return joint
    for attr in ("reasoning", "reasoning_content"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and "{" in val:
            return val
    return ""


# Modèles par défaut
MODELE_SOUVERAIN_JARVIS = "jarvis-gc:latest"
MODELES_JARVIS_GC = ["jarvis-gc:latest", "qwen2.5:3b", "qwen2.5:7b"]
MODELES_GROQ = ["openai/gpt-oss-120b"]
MODELES_OPENROUTER = ["meta-llama/llama-3.3-70b-instruct:free"]
MODELE_LOCAL = "qwen2.5:3b"


def get_modele_local() -> str:
    """Retourne le meilleur modèle Ollama disponible localement.
    
    Vérifie en priorité JARVIS_LOCAL_MODEL, puis cherche parmi les modèles
    Ollama installés le plus performant disponible, avec repli prioritaire sur 3b/1.5b.
    """
    pref = os.environ.get("JARVIS_LOCAL_MODEL")
    if pref:
        return pref
    candidates = ["qwen2.5:3b", "qwen2.5:1.5b", "qwen2.5:0.5b", "jarvis-gc:latest", "qwen2.5:7b"]
    try:
        if ollama is not None:
            models_list = ollama.list()
            raw = models_list.get("models", []) if isinstance(models_list, dict) else getattr(models_list, "models", [])
            installed = [m.get("model", m.get("name", "")) if isinstance(m, dict) else getattr(m, "model", getattr(m, "name", "")) for m in raw]
            installed = [m for m in installed if m]
            for c in candidates:
                for inst in installed:
                    if c == inst or inst.startswith(c + ":") or inst == f"{c}:latest":
                        return inst
    except Exception:
        pass
    return MODELE_LOCAL


def prechauffer_modele_local(modele: Optional[str] = None) -> None:
    """Pré-charge le modèle local en RAM/VRAM en tâche de fond pour éliminer le cold start."""
    nom = modele or get_modele_local()

    def _worker():
        try:
            if ollama is not None:
                ollama.generate(model=nom, prompt="", keep_alive="5m")
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True, name="OllamaPrewarm")
    t.start()


_EVENT_EMITTER: Optional[Callable[[str, dict], None]] = None

# Console Rich singleton — instanciée une seule fois pour éviter les allocations
# répétées lors d'appels LLM fréquents (generate_with_fallback).
try:
    from rich.console import Console as _RichConsole
    _CONSOLE = _RichConsole()
except ImportError:
    _CONSOLE = None  # type: ignore[assignment]


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
        **kwargs,
    ) -> LLMResponse:
        raise NotImplementedError


class GroqProvider(BaseLLMProvider):
    """Fournisseur Groq avec support multi-clés, timeout strict de 5s par clé et rotation sur erreur/429."""

    def __init__(self, modeles: Optional[list[str]] = None, timeout_per_key: float = 5.0):
        super().__init__(
            nom="Groq",
            modeles=modeles or MODELES_GROQ,
            niveau="simple",
        )
        self.timeout_per_key = timeout_per_key

    def get_clients(self) -> list:
        if GroqClient is None:
            return []
        clients = []
        i = 1
        while True:
            key = os.environ.get(f"GROQ_API_KEY_{i}")
            if not key:
                break
            clients.append(GroqClient(api_key=key, timeout=self.timeout_per_key))
            i += 1
        if not clients and os.environ.get("GROQ_API_KEY"):
            clients.append(GroqClient(api_key=os.environ.get("GROQ_API_KEY"), timeout=self.timeout_per_key))
        return clients

    def is_available(self) -> bool:
        return len(self.get_clients()) > 0

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
        on_key_failure: Optional[Callable[[str, Exception], None]] = None,
        **kwargs,
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

        modele_raisonnement = "gpt-oss" in (modele or "")
        budget = max(int(cfg.max_tokens or 1024), 4096 if modele_raisonnement else 1024)

        for idx, client in enumerate(clients):
            try:
                call_kwargs = {
                    "model": modele,
                    "messages": groq_messages,
                    "max_tokens": budget,
                    "temperature": cfg.temperature,
                    "timeout": self.timeout_per_key,
                }
                if modele_raisonnement:
                    call_kwargs["reasoning_effort"] = "low"
                try:
                    response = client.chat.completions.create(**call_kwargs)
                except TypeError:
                    call_kwargs.pop("reasoning_effort", None)
                    response = client.chat.completions.create(**call_kwargs)
                msg = response.choices[0].message
                contenu = _extraire_texte_message_llm(msg)
                if not str(contenu or "").strip():
                    raise RuntimeError(
                        f"Groq {modele} a renvoyé un contenu vide "
                        f"(finish_reason={getattr(response.choices[0], 'finish_reason', None)})."
                    )
                return LLMResponse(
                    content=contenu,
                    provider=self.nom,
                    model=modele,
                    raw=response,
                )
            except Exception as e:
                derniere_erreur = e
                if on_key_failure is not None:
                    on_key_failure(f"Groq (clé {idx + 1})", e)
                if "429" in str(e):
                    continue
                # Si plusieurs clés configurées et que ce n'est pas la dernière, tester la suivante
                if len(clients) > 1 and idx < len(clients) - 1:
                    continue
                raise RuntimeError(f"Groq error: {e}") from e

        raise RuntimeError(f"Groq error (toutes clés épuisées): {derniere_erreur}")


class OpenRouterProvider(BaseLLMProvider):
    """Fournisseur OpenRouter avec injection de prompt système, rotation multi-clés et timeout maximal de 10s."""

    def __init__(self, modeles: Optional[list[str]] = None, timeout: float = 10.0):
        super().__init__(
            nom="OpenRouter",
            modeles=modeles or MODELES_OPENROUTER,
            niveau="simple",
        )
        self.default_timeout = timeout

    def get_api_keys(self) -> list[str]:
        keys = []
        i = 1
        while True:
            k = os.environ.get(f"OPENROUTER_API_KEY_{i}")
            if not k:
                break
            keys.append(k)
            i += 1
        if not keys and os.environ.get("OPENROUTER_API_KEY"):
            keys.append(os.environ.get("OPENROUTER_API_KEY"))
        return keys

    def is_available(self) -> bool:
        return len(self.get_api_keys()) > 0

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
        on_key_failure: Optional[Callable[[str, Exception], None]] = None,
        **kwargs,
    ) -> LLMResponse:
        cfg = config or LLMConfig(max_tokens=2048)
        api_keys = self.get_api_keys()
        if not api_keys:
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

        # 5s par clé si plusieurs clés, sinon plafond demandé de 10s
        timeout_req = 5.0 if len(api_keys) > 1 else self.default_timeout
        derniere_erreur = None

        for idx, key in enumerate(api_keys):
            request = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://localhost/jarvis",
                    "X-Title": "Jarvis Local",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_req) as response:
                    data = json.loads(response.read().decode("utf-8"))
                contenu = data["choices"][0]["message"]["content"]
                return LLMResponse(
                    content=contenu,
                    provider=self.nom,
                    model=modele,
                    raw=data,
                )
            except Exception as e:
                derniere_erreur = e
                if on_key_failure is not None:
                    on_key_failure(f"OpenRouter (clé {idx + 1})", e)
                if len(api_keys) > 1 and idx < len(api_keys) - 1:
                    continue
                raise RuntimeError(f"OpenRouter error: {e}") from e

        raise RuntimeError(f"OpenRouter error (toutes clés épuisées): {derniere_erreur}")


class OllamaProvider(BaseLLMProvider):
    """Fournisseur Ollama local avec auto-détection du modèle et timeout protecteur anti-freeze."""

    def __init__(self, modele: Optional[str] = None, timeout: float = 25.0):
        nom_modele = modele or get_modele_local()
        super().__init__(
            nom="Ollama",
            modeles=[nom_modele],
            niveau="local",
        )
        self.timeout = timeout

    def is_available(self) -> bool:
        return ollama is not None

    def generate(
        self,
        modele: str,
        messages: list[dict],
        config: Optional[LLMConfig] = None,
        **kwargs,
    ) -> LLMResponse:
        if ollama is None:
            raise RuntimeError("Module ollama non disponible.")
        cfg = config or LLMConfig()
        options = {"think": False, "temperature": cfg.temperature}
        options.update(cfg.extra_options)

        def _call_ollama():
            return ollama.chat(
                model=modele,
                messages=messages,
                options=options,
            )

        timeout_val = cfg.timeout or self.timeout
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_ollama)
                response = future.result(timeout=timeout_val)

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
        except concurrent.futures.TimeoutError:
            raise RuntimeError(f"Ollama a dépassé le délai de {timeout_val}s pour générer.")
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
            "num_ctx": int(os.environ.get("JARVIS_GC_NUM_CTX", 4096)),
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
        require_json: bool = False,
    ) -> Optional[dict]:
        """
        Génère une réponse avec cascade de haute performance :
        1. Cloud Ultra-Rapide (Groq / OpenRouter) en Priorité #1 pour réactivité instantanée (< 1s) et intelligence maximale (120B/70B).
        2. Modèle Souverain The Great Corporation (Jarvis-GC) en Fallback Hors-Ligne #1 si le cloud est inaccessible.
        3. Modèle local standard (Ollama fallback) en dernier recours.
        """
        cfg = config or LLMConfig()
        mem = memoire or {}
        # Utiliser le singleton module-level ; recréer uniquement si absent (import optionnel).
        if _CONSOLE is not None:
            console = _CONSOLE
        else:
            from rich.console import Console
            console = Console()

        # Modèle local prévu pour le secours
        modele_local = self.local_provider.modeles[0] if (self.local_provider and getattr(self.local_provider, "modeles", None)) else get_modele_local()

        # Compteur d'échecs pour déclenchement anticipé du pré-chargement en mémoire vive
        echecs_cloud = 0
        prewarm_lance = False

        def notifier_echec_cle(source: str = "Cloud", err: Optional[Exception] = None):
            nonlocal echecs_cloud, prewarm_lance
            echecs_cloud += 1
            if echecs_cloud >= 3 and not prewarm_lance:
                prewarm_lance = True
                console.print(f"[dim yellow]⚡ 3 échecs de clés/providers cloud ({source}) -> Pré-chargement anticipé en RAM de {modele_local}...[/dim yellow]")
                if on_event is not None:
                    on_event("thinking", {"message": f"Pré-chargement du modèle de secours ({modele_local})..."})
                prechauffer_modele_local(modele_local)

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
                        try:
                            resp = provider.generate(modele, messages, config=cfg, on_key_failure=notifier_echec_cle)
                        except TypeError:
                            resp = provider.generate(modele, messages, config=cfg)
                        if not str(getattr(resp, "content", "") or "").strip():
                            raise RuntimeError(f"{nom} {modele} a renvoyé une réponse vide")
                        if require_json and "{" not in str(resp.content):
                            raise RuntimeError(f"{nom} {modele} a renvoyé une réponse sans JSON")
                        console.print(f"[dim green]✓ {nom} réussi : {modele}[/dim green]")
                        if on_event is not None:
                            on_event("provider", {"provider": nom, "model": modele})
                        self.memoriser_provider_cloud(nom)
                        return resp.to_dict()
                    except Exception as e:
                        notifier_echec_cle(nom, e)
                        console.print(f"[dim yellow]✗ {nom} {modele} indisponible : {str(e)[:100]}[/dim yellow]")
                        continue

            # 2. FALLBACK SOUVERAIN HORS-LIGNE (The Great Corporation Jarvis-GC)
            if self.sovereign_provider and self.sovereign_provider.is_available():
                modele_souverain = self.sovereign_provider.modeles[0]
                try:
                    console.print(f"[dim cyan]-> Mode Hors-Ligne : Modèle Souverain The Great Corporation actif ({modele_souverain})...[/dim cyan]")
                    resp = self.sovereign_provider.generate(modele_souverain, messages, config=cfg)
                    if not str(getattr(resp, "content", "") or "").strip():
                        raise RuntimeError("Jarvis-GC a renvoyé une réponse vide")
                    if require_json and "{" not in str(resp.content):
                        raise RuntimeError("Jarvis-GC a renvoyé une réponse sans JSON")
                    console.print(f"[dim green]✓ {self.sovereign_provider.nom} réussi : {modele_souverain}[/dim green]")
                    if on_event is not None:
                        on_event("provider", {"provider": self.sovereign_provider.nom, "model": modele_souverain})
                    return resp.to_dict()
                except Exception as e:
                    console.print(f"[dim yellow]✗ {self.sovereign_provider.nom} indisponible ({str(e)[:100]}) -> Fallback local standard[/dim yellow]")

            # 3. FALLBACK LOCAL STANDARD
            modele_local = self.local_provider.modeles[0] if (self.local_provider and getattr(self.local_provider, "modeles", None)) else get_modele_local()
            if tentative == 0:
                console.print(f"[dim]-> Utilisation du modèle local : {modele_local}[/dim]")
            try:
                resp = self.local_provider.generate(modele_local, messages, config=cfg)
                if not str(getattr(resp, "content", "") or "").strip():
                    raise RuntimeError("Ollama a renvoyé une réponse vide")
                if require_json and "{" not in str(resp.content):
                    raise RuntimeError("Ollama a renvoyé une réponse sans JSON")
                if on_event is not None:
                    on_event("provider", {"provider": self.local_provider.nom, "model": modele_local})
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
        dernier_niveau = routeur.get(f"dernier_provider_{niveau}")
        noms = [p["nom"] for p in groupe]
        if dernier_niveau in noms:
            index_suivant = (noms.index(dernier_niveau) + 1) % len(groupe)
            groupe = groupe[index_suivant:] + groupe[:index_suivant]
        elif dernier_global in noms:
            idx = noms.index(dernier_global)
            groupe = [groupe[idx]] + [p for i, p in enumerate(groupe) if i != idx]
        ordonnes.extend(groupe)
    return ordonnes


def memoriser_provider_cloud(nom_provider: str) -> None:
    _DEFAULT_CLIENT.memoriser_provider_cloud(nom_provider)
