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

# Mots de validation : l'utilisateur confirme une action proposée par Jarvis
MOTS_VALIDATION = [
    "oui", "vas-y", "soit", "fais-le", "fais le", "ok fais", "lance",
    "go", "allez", "parfait fais", "fais", "procède", "execute",
    "continue", "confirme", "d'accord fais", "oui jarvis",
]


def detecter_intention(message: str) -> bool:
    message_lower = message.lower()
    PATTERNS_CONVERSATION = [
        r"\bpourquoi\b", r"\bcomment\b", r"\bqu[' ]est-ce\b",
        r"\bexplique\b", r"\bdis-moi\b", r"\bqui es-tu\b",
        r"\bes-tu\b", r"\bsais-tu\b", r"\bmerci\b",
        r"\bd[' ]accord\b", r"\bok\b", r"\bbonjour\b",
        r"\bque se passe\b", r"\bvide\b", r"\bcontient\b",
        r"\bsouviens\b", r"\braconte\b", r"\bqu[' ]as-tu\b",
        r"\bl[' ]as-tu\b", r"\bqu[' ]y a-t-il\b"
    ]
    for pattern in PATTERNS_CONVERSATION:
        if re.search(pattern, message_lower):
            return False
    VERBES_ACTION = [
        "ouvre", "ferme", "lance", "crée", "supprime", "déplace",
        "copie", "liste", "lis", "écris", "exécute", "installe",
        "trouve", "cherche", "analyse", "surveille", "démarre", "arrête",
        "organise", "note", "mémorise", "rappelle", "vide", "notifie"
    ]
    CIBLES_SYSTEME = [
        r"\b\w+\.\w{2,4}\b",
        r"[A-Z]:\\", r"/home/", r"/mnt/",
        r"\bprocessus\b", r"\bpid\b",
        r"\bram\b", r"\bcpu\b", r"\bdisque\b", r"\bstockage\b",
        r"\bdossier\b", r"\brépertoire\b", r"\bfichier\b",
        r"\btemp\b", r"\bcorbeille\b",
        r"\brappel\b", r"\bautomatisation\b", r"\bsurveillance\b",
        r"\bnote\b", r"\bpréférence\b", r"\bmémoire\b"
    ]
    has_verb = any(v in message_lower for v in VERBES_ACTION)
    has_target = any(re.search(p, message_lower) for p in CIBLES_SYSTEME)
    return has_verb and has_target


def detecter_validation(message: str, historique: list) -> bool:
    """
    Retourne True si l'utilisateur valide une action proposée par Jarvis
    dans le tour précédent. Evite de basculer en mode action sur un simple
    "oui" hors contexte d'action.
    """
    message_lower = message.lower().strip()
    # Le message doit être court (validation courte, pas une nouvelle demande)
    if len(message_lower) > 60:
        return False
    # Vérifier que c'est un mot de validation
    if not any(message_lower == v or message_lower.startswith(v + " ") for v in MOTS_VALIDATION):
        return False
    # Vérifier que le dernier message de Jarvis proposait une action
    for msg in reversed(historique):
        if msg["role"] == "assistant":
            contenu = msg["content"].lower()
            indicateurs_proposition = [
                "je peux", "voulez-vous", "souhaitez-vous", "je vais",
                "est-ce que", "dois-je", "permettez-moi", "si vous le souhaitez",
                "je pourrais", "ouvrir", "ajuster", "modifier", "lancer",
            ]
            return any(ind in contenu for ind in indicateurs_proposition)
    return False


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


def chat_with_cloud(modele, messages):
    """Appel à Groq pour modèles cloud gratuits."""
    try:
        client = GroqClient()
        groq_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        response = client.chat.completions.create(
            model=modele,
            messages=groq_messages,
            max_tokens=1024,
            temperature=0.7
        )
        return {"message": {"content": response.choices[0].message.content}}
    except Exception as e:
        raise Exception(f"Groq error: {e}")


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
    """Appel à Ollama pour modèle local avec gestion d'erreur."""
    try:
        return ollama.chat(model=modele, messages=messages, options={"think": False})
    except Exception as e:
        raise Exception(f"Ollama non disponible: {e}. Assurez-vous que le service est démarré.")


def providers_cloud_disponibles() -> list[dict]:
    providers = []
    if os.environ.get("GROQ_API_KEY"):
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
    """Choisir selon la complexite, puis alterner dans le groupe prioritaire pour repartir les quotas."""
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
    """
    Extrait les objets JSON du texte.
    Valide strictement que chaque objet a "outil" et "args" avec "args" dict.
    """
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
    """Valide que la réponse contient au moins un JSON valide avec "outil" et "args"."""
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
    """Extrait la réponse naturelle du LLM en supprimant les JSON d'outils."""
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
    """Construit la réponse finale en combinant la réponse naturelle du LLM et les résultats des outils."""
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


def parler(message: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """Parle en utilisant le modèle cloud d'abord, puis fallback sur local."""
    historique.append({"role": "user", "content": message})

    intention_action = detecter_intention(message) or detecter_validation(message, historique)
    complexite = estimer_complexite(message, intention_action)

    if intention_action:
        historique[0]["content"] = construire_prompt_action(memoire)
    else:
        historique[0]["content"] = construire_prompt_conversation(memoire)

    reponse = None
    provider_cloud_reussi = None
    tentatives = 0
    max_tentatives = 2

    while tentatives < max_tentatives:
        tentatives += 1
        providers_cloud = ordonner_providers_cloud(providers_cloud_disponibles(), memoire, complexite)

        if providers_cloud:
            if tentatives == 1:
                console.print(f"[dim]→ Cle API cloud detectee. Tentative modeles cloud...[/dim]")
            else:
                console.print(f"[dim yellow]→ Retry modeles cloud (tentative {tentatives})...[/dim yellow]")

            for provider in providers_cloud:
                if reponse is not None:
                    break
                nom_provider = provider["nom"]
                modeles = provider["modeles"]
                fonction_chat = provider["fonction"]
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(modeles)) as executor:
                    futures = {executor.submit(fonction_chat, modele, historique): modele for modele in modeles}
                    for future in concurrent.futures.as_completed(futures):
                        modele = futures[future]
                        try:
                            reponse = future.result()
                            provider_cloud_reussi = nom_provider
                            console.print(f"[dim green]✓ {nom_provider} reussi : {modele}[/dim green]")
                            break
                        except Exception as e:
                            console.print(f"[dim yellow]✗ {nom_provider} {modele} indisponible : {str(e)[:100]}[/dim yellow]")
                            continue
        else:
            if tentatives == 1:
                console.print(
                    "[dim yellow]⚠️  Aucune cle API cloud detectee "
                    "(GROQ_API_KEY ou OPENROUTER_API_KEY).[/dim yellow]"
                )

        if reponse is None:
            if tentatives == 1:
                console.print(f"[dim]→ Utilisation du modèle local : {MODELE_LOCAL}[/dim]")
            else:
                console.print(f"[dim yellow]→ Retry {MODELE_LOCAL} (tentative {tentatives})...[/dim yellow]")
            try:
                reponse = chat_with_local(MODELE_LOCAL, historique)
            except Exception as e:
                console.print(f"[red]✗ Erreur modèle local : {e}[/red]")
                if tentatives < max_tentatives:
                    continue
                reponse = {"message": {"content": f"Erreur : {e}"}}

        if reponse is None:
            continue

        contenu = reponse["message"]["content"]

        if intention_action:
            if valider_reponse_json(contenu):
                break
            elif tentatives < max_tentatives:
                console.print(f"[yellow]⚠️  Réponse invalide (pas de JSON). Nouvelle tentative...[/yellow]")
                historique.append({"role": "assistant", "content": contenu})
                historique.append({
                    "role": "user",
                    "content": "Votre réponse précédente ne contenait pas de JSON d'outil valide. Veuillez répondre avec une ligne JSON au format {\"outil\": \"nom\", \"args\": {...}}, puis une phrase naturelle."
                })
                reponse = None
                provider_cloud_reussi = None
                continue
        else:
            break

    if reponse is None:
        reponse = {"message": {"content": "Erreur : Impossible d'obtenir une réponse du modèle."}}

    contenu = reponse["message"]["content"]
    if provider_cloud_reussi:
        memoriser_provider_cloud(provider_cloud_reussi)
    historique.append({"role": "assistant", "content": contenu})
    limiter_historique(historique)
    return contenu, intention_action


def executer_agent(user_input: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """Boucle agentique courte : action, observation, correction/continuation."""
    reponse, intention_action = parler(user_input, historique, memoire)
    if not intention_action:
        return reponse, False

    complexite = estimer_complexite(user_input, intention_action)
    max_etapes = MAX_ETAPES_AGENT if complexite == "complexe" else 1
    resultats_outils = []
    reponses_llm = []

    for etape in range(1, max_etapes + 1):
        resultat = executer_outil(reponse)
        if resultat:
            resultats_outils.append(resultat)
            reponses_llm.append(reponse)
        else:
            resultats_outils.append("Erreur : aucune commande d'outil valide n'a été générée.")
            break

        if reponse_termine_tache(reponse):
            break
        if complexite != "complexe" and not resultat_indique_erreur(resultat):
            break
        if etape >= max_etapes:
            break

        observation = (
            "Observation outil :\n"
            f"{resultat}\n\n"
            "Continue la tache si necessaire avec le prochain JSON d'outil. "
            "Si tout est termine, reponds uniquement avec "
            '{"outil": "terminer_tache", "args": {"resume": "resume court du resultat"}}.'
        )
        reponse, intention_action = parler(observation, historique, memoire)
        if not intention_action:
            resultats_outils.append(reponse)
            reponses_llm.append(reponse)
            break

    return construire_reponse_finale(reponses_llm, resultats_outils), True


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
        f"JARVIS — Agent local de {nom}\nAssistant, majordome numérique et compagnon cognitif\nTape 'exit' pour quitter.",
        style="bold cyan"
    ))
    stop_event = threading.Event()
    agent = AutonomousAgent(memoire=memoire, outils=OUTILS, console=console)
    veille = threading.Thread(target=agent.run, args=(stop_event,), daemon=True)
    veille.start()
    while True:
        try:
            user_input = console.input("[bold green]Toi >[/bold green] ").strip()
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