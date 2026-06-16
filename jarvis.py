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
from core.translator import traduire_message, match_fort
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

# ─── MODE ACTION FORCÉ ────────────────────────────────────────────────────────
mode_action_force = False

PATTERNS_ACTIVATION_MODE_ACTION = [
    r"\bpasse en mode action\b",
    r"\bmode action\b",
]
PATTERNS_DESACTIVATION_MODE_ACTION = [
    r"\bpasse en mode conversation\b",
    r"\bmode conversation\b",
    r"\bmode conv\b",
    r"\bonv\b",
]
RACCOURCI_MODE_ACTION = "!a"
RACCOURCI_MODE_STARK = "!S"

def detecter_commande_mode(message: str) -> str | None:
    """Retourne 'action', 'conv', 'stark', 'stark_off', ou None."""
    m = message.lower().strip()
    if m == RACCOURCI_MODE_ACTION:
        return "action"
    if m == RACCOURCI_MODE_STARK:
        return "stark"
    if any(re.search(p, m) for p in PATTERNS_ACTIVATION_MODE_ACTION):
        return "action"
    if any(re.search(p, m) for p in PATTERNS_DESACTIVATION_MODE_ACTION):
        return "conv"
    return None
# ─────────────────────────────────────────────────────────────────────────────


def detecter_intention(message: str) -> bool:
    global mode_action_force

    # Court-circuit : mode action one-shot activé
    if mode_action_force:
        return True

    message_lower = message.lower()

    # Patterns conversation pure — NETTOYÉS des faux positifs
    PATTERNS_CONVERSATION = [
        r"\bpourquoi\b", r"\bcomment\b", r"\bqu[' ]est-ce\b",
        r"\bexplique\b", r"\bdis-moi\b", r"\bqui es-tu\b",
        r"\bes-tu\b", r"\bsais-tu\b", r"\bmerci\b",
        r"\bd[' ]accord\b", r"\bbonjour\b",
        r"\bque se passe\b", r"\braconte\b",
        # RETIRÉS volontairement : r"\bvide\b", r"\bcontient\b",
        # r"\bsouviens\b", r"\bqu[' ]as-tu\b", r"\bl[' ]as-tu\b",
        # r"\bqu[' ]y a-t-il\b", r"\bok\b"
        # → bloquaient des intentions légitimes
    ]
    for pattern in PATTERNS_CONVERSATION:
        if re.search(pattern, message_lower):
            return False

    VERBES_ACTION = [
        # existants
        "ouvre", "ferme", "lance", "crée", "supprime", "déplace",
        "copie", "liste", "écris", "exécute", "installe",
        "trouve", "cherche", "analyse", "surveille", "démarre", "arrête",
        "organise", "note", "mémorise", "rappelle", "vide", "notifie",
        # ajouts
        "fouille", "vérifie", "verifie", "check", "affiche", "montre",
        "scanne", "inspecte", "ajoute", "enregistre", "sauvegarde",
        "efface", "nettoie", "libère", "libere",
        "consulte", "accède", "accede",
        "demarre", "stoppe", "tue", "kill",
        "planifie", "programme", "automatise",
        "renomme", "deplace",
        "audite", "optimise", "diagnostique", "recherche",
    ]

    CIBLES_SYSTEME = [
        # existantes
        r"\b\w+\.\w{2,4}\b",
        r"[A-Z]:\\", r"/home/", r"/mnt/",
        r"\bprocessus\b", r"\bpid\b",
        r"\bram\b", r"\bcpu\b", r"\bdisque\b", r"\bstockage\b",
        r"\bdossier\b", r"\brépertoire\b", r"\bfichier\b",
        r"\btemp\b", r"\bcorbeille\b",
        r"\brappel\b", r"\bautomatisation\b", r"\bsurveillance\b",
        r"\bnote\b", r"\bpréférence\b", r"\bmémoire\b",
        # ajouts — mémoire & contexte
        r"\bmemoire\b", r"\bcontexte\b", r"\bprofil\b",
        r"\bpreference\b", r"\bpreferences\b",
        # ajouts — système & apps
        r"\blogs?\b", r"\bjournal\b", r"\bévenements?\b", r"\bevenements?\b",
        r"\bservices?\b", r"\bparamètres?\b", r"\bparametres?\b",
        r"\bapplication\b", r"\bappli\b", r"\bapp\b",
        r"\bexplorateur\b", r"\bterminal\b", r"\bconsole\b",
        r"\btâche\b", r"\btache\b", r"\bregistre\b",
        r"\bprogramme\b", r"\bperformance\b", r"\bprocesseur\b",
        r"\bwindows\b", r"\bsystème\b", r"\bsysteme\b",
        r"\bhistorique\b", r"\bconfiguration\b", r"\bconfig\b",
        # ajouts — outils réels
        r"\bcommande\b", r"\bscript\b", r"\bpowershell\b",
        r"\bautomatisations?\b", r"\bplanification\b",
        r"\bsurveillances?\b", r"\bwatcher\b",
        r"\bbilan\b", r"\baudit\b", r"\brapport\b",
        r"\bespace\b", r"\boccupation\b",
        r"\bnotification\b", r"\balerte\b",
        r"\béchange\b", r"\bechange\b",
    ]

    # Cibles fortes : déclenchent action même sans verbe explicite
    # Limitées aux mots qui n'apparaissent JAMAIS en conversation pure
    CIBLES_FORTES = [
        r"\brappels?\b",
        r"\bautomatisations?\b",
        r"\bbilan\b",
        r"\baudit\b",
        r"\bpowershell\b",
        r"\bwatcher\b",
        r"\bpreferences?\b",
        r"\bplanification\b",
    ]

    # Patterns interrogation d'état : "Y'a-t-il des rappels ?", "Ai-je des notes ?"
    # Combinés à une cible système → action
    PATTERNS_INTERROGATION_ETAT = [
        r"\by[' ]a[\s-]t[\s-]il\b",
        r"\bai-je\b",
        r"\best-ce qu[' ]il y a\b",
        r"\bqu[' ]est-ce qu[' ]il y a\b",
        r"\bmontre[\s-]moi\b",
        r"\bc[' ]est quoi\b",
        r"\bqu[' ]as-tu\b",
        r"\bl[' ]as-tu\b",
    ]

    has_verb = any(v in message_lower for v in VERBES_ACTION)
    has_target = any(re.search(p, message_lower) for p in CIBLES_SYSTEME)
    has_strong_target = any(re.search(p, message_lower) for p in CIBLES_FORTES)
    has_interrogation_etat = any(re.search(p, message_lower) for p in PATTERNS_INTERROGATION_ETAT)

    # Logique de décision
    if has_verb and has_target:
        return True
    if has_strong_target:
        return True
    if has_interrogation_etat and has_target:
        return True
    return False


def detecter_validation(message: str, historique: list) -> bool:
    message_lower = message.lower().strip()
    if len(message_lower) > 60:
        return False
    if not any(message_lower == v or message_lower.startswith(v + " ") for v in MOTS_VALIDATION):
        return False
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


def parler(message: str, historique: list, memoire: dict) -> tuple[str, bool]:
    global mode_action_force

    # ── Gestion commandes de mode ─────────────────────────────────────────────
    commande_mode = detecter_commande_mode(message)
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
    elif commande_mode == "stark":
        activer_mode_stark()
        msg_confirm = "Mode Stark activé, Sir. Accès étendu autorisé. JARVIS_DIR reste protégé."
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

    # ── NOUVELLE ARCHITECTURE : Core Intellect ───────────────────────────────
    # Le traducteur pré-résout les intentions connues (optimisation)
    langue = memoire.get("utilisateur", {}).get("langue", "français")
    traduction = traduire_message(message, langue[:2].lower())
    
    if traduction and match_fort(message, langue[:2].lower()):
        # Match fort : intention déjà résolue, Core Intellect valide uniquement
        cle, intention_pre_resolue = traduction
        console.print(f"[dim cyan]→ Intention pré-résolue : {cle}[/dim cyan]")
        # Pour l'instant, on passe quand même par Core Intellect pour validation
        # À l'avenir, on pourra exécuter directement si confiance élevée
    
    # Core Intellect comprend l'objectif réel en une seule passe LLM
    resultat_intellect = interpreter_objectif(message, historique, memoire)
    
    objectif = resultat_intellect["objectif"]
    type_demande = resultat_intellect["type"]
    actions = resultat_intellect["actions"]
    reponse_naturelle = resultat_intellect["reponse"]
    
    # Déterminer si c'est une action (pour compatibilité avec le code existant)
    intention_action = type_demande in {"action", "mixte"} or len(actions) > 0
    
    # Si mode action one-shot était actif, forcer l'action
    if etait_mode_action_force:
        intention_action = True
    
    # ─────────────────────────────────────────────────────────────────────────

    # Mise à jour de la mémoire
    memoire.update(normaliser_memoire(charger_memoire()))

    # Construire la réponse finale avec les actions exécutées
    if actions:
        # Exécuter les actions
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
        
        # Enrichir la réponse avec les résultats
        if resultats_outils:
            reponse_finale = f"{reponse_naturelle}\n\n" + "\n".join(resultats_outils)
        else:
            reponse_finale = reponse_naturelle
    else:
        reponse_finale = reponse_naturelle
    
    historique.append({"role": "assistant", "content": reponse_finale})
    limiter_historique(historique)
    return reponse_finale, intention_action


def executer_agent(user_input: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """
    Exécute une requête utilisateur avec le nouveau flux Core Intellect.
    
    Core Intellect gère déjà la compréhension et l'exécution des actions
    en une seule passe LLM. Cette fonction simplifiée sert d'interface
    pour la boucle principale.
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
        f"Mode Stark (accès étendu) : '!S'",
        style="bold cyan"
    ))
    stop_event = threading.Event()
    agent = AutonomousAgent(memoire=memoire, outils=OUTILS, console=console)
    veille = threading.Thread(target=agent.run, args=(stop_event,), daemon=True)
    veille.start()
    while True:
        try:
            mode_label = "[bold magenta]⚡ACTION > [/bold magenta]" if mode_action_force else "[bold green]Toi > [/bold green]"
            if est_mode_stark_actif():
                mode_label = "[bold red]⚡STARK > [/bold red]"
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