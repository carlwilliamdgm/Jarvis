import concurrent.futures
import json
import ollama
import os
import platform
import re
import threading
import time
import urllib.request
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from groq import Groq as GroqClient
from rich.console import Console
from rich.panel import Panel
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.prompt import construire_prompt_action, construire_prompt_conversation
from core.intellect import interpreter_objectif
from core.safety import activer_mode_stark, desactiver_mode_stark, est_mode_stark_actif
from tools import OUTILS

try:
    import psutil
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "psutil", "-q"])
    import psutil

console = Console()

OS = platform.system()
HOME = Path.home()

MODELES_GROQ = ["llama-3.3-70b-versatile"]
MODELES_OPENROUTER = ["meta-llama/llama-3.3-70b-instruct:free"]
MODELE_LOCAL = "qwen2.5:7b"
MAX_MESSAGES_HISTORIQUE = 20
MAX_ETAPES_AGENT = 5
MAX_ETAPES_STARK = 10

MOTS_ACTION = [
    "fais", "crée", "supprime", "liste", "exécute", "commande",
    "dossier", "fichier", "mémoire", "note", "préférence",
    "rappel", "creer", "lire", "audit", "vider",
    "ajouter", "noter", "memoriser", "nettoyer", "liberer", "optimise",
    "renomme", "deplace", "copie", "synchronise", "planifie", "rappelle"
]

MOTS_CONVERSATION = [
    "que se passe", "pourquoi", "comment", "qu'est-ce",
    "explique", "dis-moi", "raconte", "d'accord", "ok",
    "merci", "qui es-tu", "es-tu", "sais-tu", "savais-tu",
]

MOTS_OPTIMISATION = ["optimise", "libère", "nettoie", "libere", "nettoyer"]
MOTS_COMPLEXES = [
    "analyse", "audite", "audit", "corrige", "debug", "diagnostique", "optimise",
    "refactor", "architecture", "complexe", "plan", "projet", "automatisation",
    "surveillance", "organise", "plusieurs", "étapes", "etapes", "complet",
]
PLAN_OPTIMISATION = (
    "\nEnchaine les actions suivantes dans cet ordre : "
    "vider_temp, vider_corbeille, puis audit_stockage. "
    "Les outils sensibles gereront eux-memes la confirmation Oui/Non."
)

MOTS_VALIDATION = [
    "oui", "vas-y", "soit", "fais-le", "fais le", "ok fais", "lance",
    "go", "allez", "parfait fais", "fais", "procède", "execute",
    "continue", "confirme", "d'accord fais", "oui jarvis",
]

# ─── MODES : ACTION (!a) ET STARK (!S) — INDÉPENDANTS ET COMBINABLES ─────────
#
# !a  → one-shot, intention forcée pour le prochain message uniquement,
#       zones d'accès normales.
# !S <objectif> → boucle agentique complète : Jarvis planifie, exécute,
#       observe, itère jusqu'à atteindre l'objectif ou être bloqué.
#       Accès étendu (zones système/sensibles) actif uniquement pendant
#       la durée de la boucle, désactivé automatiquement à la sortie.
# !a + !S combinés : possible si !S est suivi d'un objectif one-shot —
#       les deux flags sont indépendants dans le code, pas de conflit.
# ───────────────────────────────────────────────────────────────────────────

mode_action_force = False

PATTERNS_ACTIVATION_MODE_ACTION = [
    r"\bpasse en mode action\b",
    r"\bmode action\b",
]
PATTERNS_DESACTIVATION_MODE_ACTION = [
    r"\bpasse en mode conversation\b",
    r"\bmode conversation\b",
    r"\bmode conv\b",
]
RACCOURCI_MODE_ACTION = "!a"

# Mode Stark : "!S <objectif>" — l'objectif est extrait du message
PATTERN_MODE_STARK = re.compile(r"^!s\s+(.+)$", re.IGNORECASE)


def detecter_commande_mode(message: str):
    """Retourne ('stark', objectif), 'action', 'conv', ou None."""
    m_brut = message.strip()
    m_lower = m_brut.lower()

    match_stark = PATTERN_MODE_STARK.match(m_brut)
    if match_stark:
        return ("stark", match_stark.group(1).strip())

    if m_lower == RACCOURCI_MODE_ACTION:
        return "action"
    if any(re.search(p, m_lower) for p in PATTERNS_ACTIVATION_MODE_ACTION):
        return "action"
    if any(re.search(p, m_lower) for p in PATTERNS_DESACTIVATION_MODE_ACTION):
        return "conv"
    return None
# ─────────────────────────────────────────────────────────────────────────────


def estimer_complexite(message: str, intention_action: bool) -> str:
    message_lower = message.lower()
    score = 0
    if intention_action:
        score += 1
    score += sum(1 for mot in MOTS_COMPLEXES if mot in message_lower)
    if len(message) > 240:
        score += 1
    if any(separateur in message_lower for separateur in [" puis ", " ensuite ", "\n", ";"]):
        score += 1
    if len(extraire_json_objets(message)) > 1:
        score += 1
    return "complexe" if score >= 2 else "simple"


def get_groq_clients():
    """Retourne une liste de clients Groq, un par cle API disponible.

    Cherche GROQ_API_KEY_1, GROQ_API_KEY_2, ... dans l'environnement.
    Si aucune n'est definie, retombe sur GROQ_API_KEY (compatibilite).
    """
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


def chat_with_cloud(modele, messages):
    """Appel a Groq pour modeles cloud gratuits.

    Essaie chaque cle API disponible (GROQ_API_KEY_1, _2, ...) dans l'ordre.
    Si une cle renvoie une erreur de rate limit (429), passe a la suivante.
    Toute autre erreur est levee immediatement.
    """
    groq_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    clients = get_groq_clients()
    if not clients:
        raise Exception("Aucune cle Groq configuree.")

    derniere_erreur = None
    for client in clients:
        try:
            response = client.chat.completions.create(
                model=modele,
                messages=groq_messages,
                max_tokens=1024,
                temperature=0.7
            )
            return {"message": {"content": response.choices[0].message.content}}
        except Exception as e:
            derniere_erreur = e
            if "429" in str(e):
                continue
            raise Exception(f"Groq error: {e}")

    raise Exception(f"Groq error (toutes cles epuisees): {derniere_erreur}")


def chat_with_openrouter(modele, messages):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY absente.")

    systeme = next((m["content"] for m in messages if m["role"] == "system"), "")
    autres = [m for m in messages if m["role"] != "system"]

    messages_envoyes = []
    if systeme:
        messages_envoyes.append({"role": "system", "content": systeme})

    if autres and systeme:
        premier_user = autres[0]["content"]
        autres[0] = {
            "role": "user",
            "content": f"[INSTRUCTIONS SYSTÈME - À RESPECTER STRICTEMENT]\n{systeme}\n[FIN INSTRUCTIONS]\n\n{premier_user}"
        }

    messages_envoyes.extend([{"role": m["role"], "content": m["content"]} for m in autres])

    payload = json.dumps({
        "model": modele,
        "messages": messages_envoyes,
        "max_tokens": 2048,
        "temperature": 0.7,
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
        return {"message": {"content": data["choices"][0]["message"]["content"]}}
    except Exception as e:
        raise Exception(f"OpenRouter error: {e}")


def chat_with_local(modele, messages):
    try:
        return ollama.chat(model=modele, messages=messages, options={"think": False})
    except Exception as e:
        raise Exception(f"Ollama non disponible: {e}. Assurez-vous que le service est démarré.")


def providers_cloud_disponibles() -> list[dict]:
    providers = []
    if get_groq_clients():
        providers.append({
            "nom": "Groq",
            "modeles": MODELES_GROQ,
            "fonction": chat_with_cloud,
            "niveau": "simple",
        })
    if os.environ.get("OPENROUTER_API_KEY"):
        providers.append({
            "nom": "OpenRouter",
            "modeles": MODELES_OPENROUTER,
            "fonction": chat_with_openrouter,
            "niveau": "simple",
        })
    return providers


def ordonner_providers_cloud(providers: list[dict], memoire: dict, complexite: str = "simple") -> list[dict]:
    if len(providers) <= 1:
        return providers
    priorite = ["complexe", "simple"] if complexite == "complexe" else ["simple", "complexe"]
    routeur = memoire.get("routeur_modeles", {})
    ordonnes = []
    for niveau in priorite:
        groupe = [provider for provider in providers if provider["niveau"] == niveau]
        if not groupe:
            continue
        dernier = routeur.get(f"dernier_provider_{niveau}")
        noms = [provider["nom"] for provider in groupe]
        if dernier in noms:
            index_suivant = (noms.index(dernier) + 1) % len(groupe)
            groupe = groupe[index_suivant:] + groupe[:index_suivant]
        ordonnes.extend(groupe)
    return ordonnes


def memoriser_provider_cloud(nom_provider: str) -> None:
    data = normaliser_memoire(charger_memoire())
    routeur = data.setdefault("routeur_modeles", {})
    routeur["dernier_provider_cloud"] = nom_provider
    for provider in providers_cloud_disponibles():
        if provider["nom"] == nom_provider:
            routeur[f"dernier_provider_{provider['niveau']}"] = nom_provider
            break
    routeur["maj"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sauvegarder_memoire(data)


def initialiser() -> dict:
    memoire = normaliser_memoire(charger_memoire())
    if "utilisateur" not in memoire:
        console.print(Panel(
            "Bienvenue. Je suis Jarvis, votre assistant local et compagnon cognitif.\nJe vais apprendre à vous connaître et à vous assister.",
            style="bold cyan"
        ))
        nom = console.input("[bold green]Comment vous appelez-vous ?[/bold green] ").strip()
        langue = console.input("[bold green]Langue préférée ? (français/english) >[/bold green] ").strip() or "français"
        memoire["utilisateur"] = {
            "nom": nom,
            "os": OS,
            "home": str(HOME),
            "langue": langue,
        }
        memoire["notes"] = []
        memoire["preferences"] = {}
        memoire["historique_actions"] = []
        sauvegarder_memoire(memoire)
        console.print(f"[cyan]Bonjour {nom}. Je me souviendrai de vous.[/cyan]\n")
    sauvegarder_memoire(memoire)
    return memoire


def extraire_json_objets(texte: str, verbose: bool = False) -> list[dict]:
    objets = []
    decodeur = json.JSONDecoder()
    position = 0

    while position < len(texte):
        position = texte.find("{", position)
        if position == -1:
            break
        try:
            objet, fin = decodeur.raw_decode(texte[position:])
        except JSONDecodeError:
            position += 1
            continue

        if not isinstance(objet, dict):
            position += fin
            continue

        if "outil" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'outil' : {objet}[/yellow]")
            position += fin
            continue
        if "args" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'args' : {objet}[/yellow]")
            position += fin
            continue
        if not isinstance(objet["args"], dict):
            if verbose:
                console.print(f"[yellow]⚠️  'args' n'est pas un dictionnaire : {objet}[/yellow]")
            position += fin
            continue

        objets.append(objet)
        position += fin

    return objets


def valider_reponse_json(reponse: str) -> bool:
    return len(extraire_json_objets(reponse)) > 0


def executer_outil(reponse: str) -> str | None:
    objets = extraire_json_objets(reponse, verbose=True)
    if not objets:
        return None
    resultats = []
    for data in objets:
        try:
            outil = data.get("outil")
            args = data.get("args", {})
            if not outil:
                continue
            if outil not in OUTILS:
                resultats.append(f"Outil inconnu : {outil}")
                continue
            if not isinstance(args, dict):
                resultats.append(f"Arguments invalides pour {outil}.")
                continue
            resultats.append(str(OUTILS[outil](**args)))
        except TypeError as e:
            resultats.append(f"Arguments invalides pour {data.get('outil')} : {e}")
        except Exception as e:
            resultats.append(f"Erreur outil {data.get('outil')} : {e}")
    return "\n".join(resultats) if resultats else None


def reponse_termine_tache(reponse: str) -> bool:
    return any(objet.get("outil") == "terminer_tache" for objet in extraire_json_objets(reponse))


def resultat_indique_erreur(resultat: str) -> bool:
    marqueurs = ["Erreur", "Outil inconnu", "Arguments invalides", "Timeout"]
    return any(marqueur in resultat for marqueur in marqueurs)


def extraire_resume_terminer_tache(reponse: str) -> str | None:
    for objet in extraire_json_objets(reponse):
        if objet.get("outil") == "terminer_tache":
            resume = objet.get("args", {}).get("resume")
            if resume:
                return str(resume)
    return None


def extraire_reponse_naturelle(reponse: str) -> str:
    lignes = reponse.split('\n')
    lignes_naturelles = []
    skip_json = False

    for ligne in lignes:
        ligne_strip = ligne.strip()
        if ligne_strip.startswith('{') and '"outil"' in ligne_strip:
            skip_json = True
            continue
        if skip_json and ligne_strip.startswith('}'):
            skip_json = False
            continue
        if skip_json:
            continue
        if not ligne_strip and lignes_naturelles and lignes_naturelles[-1].strip().startswith('}'):
            continue
        lignes_naturelles.append(ligne)

    return '\n'.join(lignes_naturelles).strip()


def construire_reponse_finale(reponses_llm: list[str], resultats_outils: list[str]) -> str:
    if not reponses_llm:
        return "\n".join(resultats_outils) if resultats_outils else "Erreur : aucune réponse générée."

    reponse_naturelle = extraire_reponse_naturelle(reponses_llm[-1])
    texte_resultats = "\n".join(resultats_outils)

    if resultat_indique_erreur(texte_resultats):
        premiere_erreur = next(
            (ligne for ligne in texte_resultats.splitlines() if resultat_indique_erreur(ligne)),
            texte_resultats
        )
        return f"{reponse_naturelle}\n\nErreur : {premiere_erreur}"

    if reponse_naturelle and texte_resultats:
        return f"{reponse_naturelle}\n\n{texte_resultats}"
    elif reponse_naturelle:
        return reponse_naturelle
    else:
        return texte_resultats or "Action terminée."


def limiter_historique(historique: list) -> None:
    if len(historique) <= MAX_MESSAGES_HISTORIQUE + 1:
        return
    systeme = historique[:1]
    recents = historique[-MAX_MESSAGES_HISTORIQUE:]
    historique[:] = systeme + recents


# ============================================================================
# MODE STARK — BOUCLE AGENTIQUE
# ============================================================================

def executer_mode_stark(objectif: str, historique: list, memoire: dict) -> str:
    """
    Mode Stark : Jarvis reçoit un objectif et boucle de façon autonome
    (planifie → exécute → observe → itère) jusqu'à l'atteindre ou être
    bloqué. L'objectif original prime à chaque itération — il est
    réinjecté intégralement pour éviter toute dérive.

    Accès étendu (zones système/sensibles) actif uniquement pendant la
    durée de la boucle ; désactivé automatiquement à la sortie, même en
    cas d'erreur.
    """
    activer_mode_stark()
    console.print(Panel(f"Objectif : {objectif}", title="⚡ Mode Stark activé", style="bold red"))

    etapes_realisees: list[str] = []

    try:
        for etape in range(1, MAX_ETAPES_STARK + 1):
            historique_etapes = (
                "\n".join(etapes_realisees) if etapes_realisees else "Aucune étape réalisée encore."
            )
            message_stark = (
                f"[MODE STARK — ÉTAPE {etape}/{MAX_ETAPES_STARK}]\n\n"
                f"OBJECTIF PRINCIPAL (à atteindre, ne jamais perdre de vue) :\n{objectif}\n\n"
                f"Étapes déjà réalisées dans cette session Stark :\n{historique_etapes}\n\n"
                "Décide la ou les prochaines actions nécessaires pour avancer vers l'objectif. "
                "Si l'objectif est déjà atteint, ou si tu es bloqué et qu'aucune action supplémentaire "
                "n'aide, appelle terminer_tache avec un résumé clair de ce qui a été fait et pourquoi tu t'arrêtes."
            )

            with console.status(f"[red]⚡ Stark réfléchit (étape {etape}/{MAX_ETAPES_STARK})...[/red]", spinner="dots"):
                resultat = interpreter_objectif(message_stark, historique, memoire)

            actions = resultat.get("actions", [])
            reponse_naturelle = resultat.get("reponse", "")

            if not actions:
                console.print(f"[red]⚡ Stark — aucune action proposée, fin de boucle.[/red]")
                rapport = (
                    f"Mode Stark terminé (étape {etape}).\n"
                    f"Objectif : {objectif}\n\n"
                    f"{reponse_naturelle}\n\n"
                    f"Étapes réalisées :\n{historique_etapes}"
                )
                return rapport

            terminer = False
            resume_final = None

            for action in actions:
                outil = action.get("outil")
                args = action.get("args", {})

                if outil == "terminer_tache":
                    resume_final = args.get("resume", "Objectif atteint.")
                    terminer = True
                    continue

                if outil not in OUTILS:
                    etapes_realisees.append(f"Étape {etape} : outil inconnu '{outil}' — ignoré")
                    console.print(f"[yellow]⚡ Outil inconnu ignoré : {outil}[/yellow]")
                    continue

                try:
                    resultat_outil = OUTILS[outil](**args)
                    etapes_realisees.append(f"Étape {etape} : {outil}({args}) → {resultat_outil}")
                    console.print(f"[dim red]⚡ {outil} → {str(resultat_outil)[:120]}[/dim red]")
                except TypeError as e:
                    etapes_realisees.append(f"Étape {etape} : {outil} → ERREUR arguments : {e}")
                    console.print(f"[red]⚡ Erreur arguments {outil} : {e}[/red]")
                except Exception as e:
                    etapes_realisees.append(f"Étape {etape} : {outil} → ERREUR : {e}")
                    console.print(f"[red]⚡ Erreur {outil} : {e}[/red]")

            if terminer:
                console.print(Panel(resume_final, title="⚡ Mode Stark — objectif atteint", style="bold green"))
                rapport = (
                    f"Mode Stark terminé avec succès.\n"
                    f"Objectif : {objectif}\n\n"
                    f"{resume_final}\n\n"
                    f"Étapes réalisées :\n" + "\n".join(etapes_realisees)
                )
                return rapport

        # Limite d'étapes atteinte sans conclusion explicite
        rapport = (
            f"Mode Stark — limite de {MAX_ETAPES_STARK} étapes atteinte sans conclusion explicite.\n"
            f"Objectif : {objectif}\n\n"
            f"Étapes réalisées :\n" + "\n".join(etapes_realisees)
        )
        console.print(Panel(rapport, title="⚡ Mode Stark — limite atteinte", style="bold yellow"))
        return rapport

    finally:
        desactiver_mode_stark()


def parler(message: str, historique: list, memoire: dict) -> tuple[str, bool]:
    global mode_action_force

    # ── Gestion commandes de mode ─────────────────────────────────────────────
    commande_mode = detecter_commande_mode(message)

    if isinstance(commande_mode, tuple) and commande_mode[0] == "stark":
        objectif = commande_mode[1]
        historique.append({"role": "user", "content": message})
        rapport = executer_mode_stark(objectif, historique, memoire)
        historique.append({"role": "assistant", "content": rapport})
        limiter_historique(historique)
        return rapport, True

    if commande_mode == "action":
        mode_action_force = True
        msg_confirm = "Mode action activé, Sir. Prochain message traité comme commande directe."
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": msg_confirm})
        return msg_confirm, False
    elif commande_mode == "conv":
        mode_action_force = False
        msg_confirm = "Mode conversation rétabli, Sir."
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": msg_confirm})
        return msg_confirm, False
    # ─────────────────────────────────────────────────────────────────────────

    historique.append({"role": "user", "content": message})

    # Si mode action one-shot : forcer intention, puis reset immédiat
    etait_mode_action_force = mode_action_force
    if mode_action_force:
        mode_action_force = False  # reset one-shot avant même le LLM
        console.print("[dim magenta]⚡ Mode action one-shot actif[/dim magenta]")

    # Recharger la mémoire depuis le disque AVANT l'appel LLM
    memoire.update(normaliser_memoire(charger_memoire()))

    # Core Intellect comprend l'objectif réel en une seule passe LLM
    resultat_intellect = interpreter_objectif(message, historique, memoire)

    type_demande = resultat_intellect["type"]
    actions = resultat_intellect["actions"]
    reponse_naturelle = resultat_intellect["reponse"]

    intention_action = type_demande in {"action", "mixte"} or len(actions) > 0
    if etait_mode_action_force:
        intention_action = True

    # Exécuter les actions retournées par Core Intellect
    resultats_outils = []
    for action in actions:
        outil = action.get("outil")
        args = action.get("args", {})
        if outil and outil in OUTILS:
            try:
                resultat = OUTILS[outil](**args)
                resultats_outils.append(str(resultat))
            except Exception as e:
                resultats_outils.append(f"Erreur outil {outil} : {e}")

    if resultats_outils:
        reponse_finale = f"{reponse_naturelle}\n\n" + "\n".join(resultats_outils)
    else:
        reponse_finale = reponse_naturelle

    historique.append({"role": "assistant", "content": reponse_finale})
    limiter_historique(historique)
    return reponse_finale, intention_action


def executer_agent(user_input: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """
    Exécute une requête utilisateur. Core Intellect gère la compréhension
    et l'exécution en une seule passe (mode normal/action), ou via la
    boucle Stark (mode !S). Cette fonction sert d'interface pour la
    boucle principale.
    """
    reponse, intention_action = parler(user_input, historique, memoire)
    return reponse, intention_action


class AutonomousAgent:
    def __init__(self, memoire, outils, console):
        self.memoire = memoire
        self.outils = outils
        self.console = console
        self.observation_interval = 60
        self.last_observations = {}
        self.consecutive_silence = 0
        self.signal_counts = {}
        self.notification_results = []
        self.last_action_time = {}

    def observer_machine(self) -> dict:
        top_processes = []
        for proc in psutil.process_iter(["name", "cpu_percent", "username"]):
            try:
                info = proc.info
                cpu = info.get("cpu_percent") or 0
                if cpu == 0:
                    continue
                top_processes.append({
                    "name": info.get("name") or "processus inconnu",
                    "cpu_percent": cpu,
                    "username": info.get("username"),
                })
            except psutil.Error:
                continue
        top_processes = sorted(top_processes, key=lambda p: p["cpu_percent"], reverse=True)[:5]
        return {
            "cpu": psutil.cpu_percent(interval=1),
            "ram": psutil.virtual_memory().percent,
            "disk_free_gb": psutil.disk_usage(str(HOME)).free / 1e9,
            "top_processes": top_processes,
            "net": psutil.net_io_counters()._asdict(),
        }

    def detecter_signaux(self, etat: dict) -> list[str]:
        COOLDOWN = 1800
        signaux = []
        detected = {}
        if etat["cpu"] > 85:
            detected["cpu_critique"] = f"CPU critique: {etat['cpu']}%"
        if etat["ram"] > 90:
            detected["ram_critique"] = f"RAM critique: {etat['ram']}%"
        if etat["disk_free_gb"] < 5:
            detected["stockage_critique"] = f"Stockage critique: {etat['disk_free_gb']:.1f}GB libres"

        previous_names = {
            proc.get("name")
            for proc in self.last_observations.get("top_processes", [])
            if proc.get("name")
        }
        for proc in etat.get("top_processes", []):
            name = proc.get("name")
            cpu = proc.get("cpu_percent") or 0
            if cpu > 50 and name not in previous_names:
                detected[f"process_{name}"] = f"Nouveau processus intensif: {name} ({cpu}%)"

        for key in list(self.signal_counts):
            if key not in detected:
                self.signal_counts[key] = 0
        for key, message in detected.items():
            self.signal_counts[key] = self.signal_counts.get(key, 0) + 1
            if self.signal_counts[key] >= 2 and time.time() - self.last_action_time.get(key, 0) >= COOLDOWN:
                signaux.append(message)

        rappels = self.outils["verifier_rappels"]()
        if not rappels.startswith("Aucun"):
            signaux.append(f"[routine] {rappels}")

        automatisations = self.outils["executer_automatisations_dues"]()
        if not automatisations.startswith("Aucune"):
            signaux.append(f"[routine] {automatisations}")

        return signaux

    def raisonner(self, signaux: list[str], memoire: dict) -> list[dict]:
        if not signaux:
            return []
        self.notification_results = [
            signal.removeprefix("[routine] ").strip()
            for signal in signaux
            if signal.startswith("[routine] ")
        ]
        signaux_non_routine = [signal for signal in signaux if not signal.startswith("[routine] ")]
        if not signaux_non_routine:
            return []

        messages = [
            {"role": "system", "content": construire_prompt_action(memoire)},
            {
                "role": "user",
                "content": (
                    "Signaux détectés:\n"
                    + "\n".join(signaux_non_routine)
                    + "\nDécide quelles actions prendre de manière autonome. "
                    "Réponds uniquement en JSON. Si rien à faire, réponds: "
                    '{"outil": "terminer_tache", "args": {"resume": "RAS"}}'
                ),
            },
        ]

        reponse = None
        provider_cloud_reussi = None
        providers_cloud = ordonner_providers_cloud(
            providers_cloud_disponibles(),
            memoire,
            complexite="complexe",
        )
        for provider in providers_cloud:
            if reponse is not None:
                break
            nom_provider = provider["nom"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(provider["modeles"])) as executor:
                futures = {
                    executor.submit(provider["fonction"], modele, messages): modele
                    for modele in provider["modeles"]
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        reponse = future.result()
                        provider_cloud_reussi = nom_provider
                        break
                    except Exception:
                        continue

        if reponse is None:
            try:
                reponse = chat_with_local(MODELE_LOCAL, messages)
            except Exception as e:
                self.console.print(f"[dim yellow]Agent autonome modele indisponible : {e}[/dim yellow]")
                return []

        if provider_cloud_reussi:
            memoriser_provider_cloud(provider_cloud_reussi)

        contenu = reponse["message"]["content"]
        actions = []
        for action in extraire_json_objets(contenu):
            if action.get("outil") == "terminer_tache" and action.get("args", {}).get("resume") == "RAS":
                continue
            actions.append(action)
        return actions

    def agir(self, actions: list[dict]) -> list[str]:
        from core.safety import action_bloquee

        resultats = []
        executed_actions = []
        path_keys = {"chemin", "path", "dossier", "fichier"}
        for action in actions:
            outil = action.get("outil")
            args = action.get("args", {})
            if outil not in self.outils or not isinstance(args, dict):
                continue
            blocked = False
            for key in path_keys:
                if key in args and action_bloquee(Path(args[key]).expanduser()):
                    blocked = True
                    break
            if blocked:
                continue
            try:
                resultats.append(str(self.outils[outil](**args)))
                executed_actions.append(action)
            except Exception as e:
                resultats.append(f"Erreur outil {outil} : {e}")
        now = time.time()
        stockage_tools = {"vider_temp", "vider_corbeille", "audit_stockage", "top_fichiers_lourds"}
        for action in executed_actions:
            outil = action.get("outil")
            args = action.get("args", {})
            if outil in stockage_tools:
                self.last_action_time["stockage_critique"] = now
            if outil == "notifier_utilisateur" and "ram" in str(args.get("message", "")).lower():
                self.last_action_time["ram_critique"] = now
        return resultats

    def adapter_intervalle(self, signaux: list[str]):
        if signaux:
            self.observation_interval = 30
            self.consecutive_silence = 0
        else:
            self.consecutive_silence += 1
            if self.consecutive_silence >= 3:
                self.observation_interval = 120
            else:
                self.observation_interval = 60

    def run(self, stop_event: threading.Event):
        while not stop_event.wait(self.observation_interval):
            try:
                etat = self.observer_machine()
                signaux = self.detecter_signaux(etat)
                self.adapter_intervalle(signaux)
                if signaux:
                    actions = self.raisonner(signaux, self.memoire)
                    resultats = []
                    if actions:
                        resultats = self.agir(actions)
                    meaningful = [
                        r for r in self.notification_results + resultats
                        if r and "Erreur" not in r
                    ]
                    if meaningful:
                        self.console.print(Panel(
                            "\n".join(meaningful),
                            title="Jarvis — Action autonome",
                            style="yellow"
                        ))
                    self.notification_results = []
                self.last_observations = etat
            except Exception as e:
                self.console.print(f"[dim yellow]Agent autonome: {e}[/dim yellow]")


def main():
    memoire = initialiser()
    nom = memoire["utilisateur"]["nom"]
    prompt = construire_prompt_action(memoire)
    historique = [{"role": "system", "content": prompt}]
    console.print(Panel(
        f"JARVIS — Agent local de {nom}\nAssistant, majordome numérique et compagnon cognitif\nTape 'exit' pour quitter.\n"
        f"Mode action one-shot : 'Jarvis, passe en mode action' ou '!a'\n"
        f"Mode Stark (boucle agentique, accès étendu) : '!S <objectif>'",
        style="bold cyan"
    ))
    stop_event = threading.Event()
    agent = AutonomousAgent(memoire=memoire, outils=OUTILS, console=console)
    veille = threading.Thread(target=agent.run, args=(stop_event,), daemon=True)
    veille.start()
    while True:
        try:
            if mode_action_force:
                mode_label = "[bold magenta]⚡ACTION > [/bold magenta]"
            elif est_mode_stark_actif():
                mode_label = "[bold red]⚡STARK > [/bold red]"
            else:
                mode_label = "[bold green]Toi > [/bold green]"

            user_input = console.input(mode_label).strip()
            if not user_input:
                continue
            if user_input.lower() in ("au revoir", "exit", "bye"):
                console.print("[cyan]Jarvis hors ligne.[/cyan]")
                stop_event.set()
                break

            if any(mot in user_input.lower() for mot in MOTS_OPTIMISATION):
                user_input += PLAN_OPTIMISATION

            horodatage = datetime.now().strftime("%H:%M:%S")
            with console.status("[cyan]Jarvis réfléchit...[/cyan]", spinner="dots"):
                reponse, intention_action = executer_agent(user_input, historique, memoire)

            reponse = reponse if isinstance(reponse, str) else ""
            OUTILS["enregistrer_echange"](user_input, reponse)
            console.print(Panel(reponse, title=f"Jarvis — {horodatage}", style="cyan"))

        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break


if __name__ == "__main__":
    main()