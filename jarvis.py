#jarvis.py

import concurrent.futures
import json
import ollama
import os
import platform
import queue
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from core.llm_client import (
    MODELES_GROQ,
    MODELES_OPENROUTER,
    MODELE_LOCAL,
    get_groq_clients,
    chat_with_cloud,
    chat_with_openrouter,
    chat_with_local,
    providers_cloud_disponibles,
    ordonner_providers_cloud,
    memoriser_provider_cloud,
    register_event_emitter,
    get_llm_client,
)
from rich.console import Console
from rich.panel import Panel
from rich.markup import escape

# Force UTF-8 encoding to avoid charmap errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
from core.error_classification import resultat_erreur
from core.memory import (
    charger_memoire,
    journaliser_erreur_systeme,
    normaliser_memoire,
    sauvegarder_memoire,
    signalement_erreurs_autre_recurrentes,
)
from core.prompt import construire_prompt_action, construire_prompt_conversation
from core.intellect import interpreter_objectif
from core.safety import activer_mode_stark, desactiver_mode_stark, est_mode_stark_actif
from core.stark_parser import StarkSegment, parser_objectif_stark
from core.stark_session import enregistrer_instance_stark, retirer_instance_stark, verifier_instances_stark
from core.autodestruct import schedule_autodestruction
from tools import OUTILS, demander_confirmation

import psutil

console = Console()


class EventBus:
    def __init__(self):
        self._queues = set()
        self._lock = threading.Lock()
        self._local = threading.local()

    def subscribe(self) -> queue.Queue:
        event_queue = queue.Queue()
        with self._lock:
            self._queues.add(event_queue)
        return event_queue

    def unsubscribe(self, event_queue: queue.Queue) -> None:
        with self._lock:
            self._queues.discard(event_queue)

    def bind(self, event_queue: queue.Queue) -> None:
        self._local.queue = event_queue

    def unbind(self) -> None:
        if hasattr(self._local, "queue"):
            del self._local.queue

    def emit(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "data": data}
        target_queue = getattr(self._local, "queue", None)
        if target_queue is not None:
            target_queue.put(event)


event_bus = EventBus()
register_event_emitter(event_bus.emit)

# Une interaction modifie l'historique et peut appeler le LLM. Toutes les
# surfaces (CLI, API et voix) passent donc par ce verrou process-level.
INTERACTION_LOCK = threading.Lock()

OS = platform.system()
HOME = Path.home()

MAX_MESSAGES_HISTORIQUE = 20
MAX_ETAPES_AGENT = 5
MAX_ETAPES_PAR_MICRO_OBJECTIF = 5
MAX_CONTEXTE_TENTATIVES_STARK = 4000
SEUIL_ECHECS_CONSECUTIFS_STARK = 3
SEUIL_ECHECS_RECHERCHE_WEB = 2  # Nombre max d'échecs de recherche web avant abandon
DERNIERS_DETAILS_STARK = []
ATTENTE_DETAILS_STARK = False
AUTODESTRUCT_CONFIRM_WINDOW_SEC = 30

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
    "mon tony stark", "tony stark", "que se passe-t-il", "comment fonctionnes",
    "comment fonctionnes-tu", "qui es-tu vraiment", "c'est quoi", "c'est quoi",
    "qu'est-ce que c'est", "dis le moi", "raconte-moi", "explique-moi",
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

MOTS_ACQUITTEMENT = [
    "parfait", "ok", "d'accord", "merci", "super", "génial", 
    "genial", "bien", "top", "nickel", "impeccable", "excellent",
    "bravo", "chouette", "formidable", "parfaitement",
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


@dataclass
class EtatAutodestruction:
    statut: str = "attente_declenchement"
    deadline: float | None = None


etat_autodestruction = EtatAutodestruction()


def _normaliser_commande_autodestruction(message: str) -> str:
    normalisee = message.casefold().strip()
    normalisee = re.sub(r"[^\w]+", " ", normalisee, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalisee).strip()


def _est_declenchement_autodestruction(message: str) -> bool:
    return _normaliser_commande_autodestruction(message) == "jarvis auto destruction"


def _est_confirmation_autodestruction(message: str) -> bool:
    return _normaliser_commande_autodestruction(message) == "jarvis confirme auto destruction"


def _gerer_autodestruction(message: str) -> tuple[bool, str | None, bool]:
    now = time.time()

    if etat_autodestruction.statut == "attente_confirmation":
        if etat_autodestruction.deadline is not None and now > etat_autodestruction.deadline:
            console.log("Demande d'auto-destruction expiree sans confirmation.")
            etat_autodestruction.statut = "attente_declenchement"
            etat_autodestruction.deadline = None
        elif _est_confirmation_autodestruction(message):
            etat_autodestruction.statut = "attente_declenchement"
            etat_autodestruction.deadline = None
            schedule_autodestruction(delay_sec=2)
            return True, "Confirmation reçue, Sir. Teardown local lancé.", True
        else:
            etat_autodestruction.statut = "attente_declenchement"
            etat_autodestruction.deadline = None
            console.log("Demande d'auto-destruction annulee par entree non conforme.")
            return True, "Auto-destruction annulée. Il faudra recommencer depuis le déclenchement, Sir.", False

    if _est_declenchement_autodestruction(message):
        etat_autodestruction.statut = "attente_confirmation"
        etat_autodestruction.deadline = now + AUTODESTRUCT_CONFIRM_WINDOW_SEC
        return (
            True,
            (
                "Auto-destruction demandée. Confirmez dans les "
                f"{AUTODESTRUCT_CONFIRM_WINDOW_SEC} secondes avec : "
                "Jarvis, confirme auto-destruction"
            ),
            False,
        )

    return False, None, False


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
            resultat = OUTILS[outil](**args)
            _journaliser_resultat_si_erreur(resultat, "mode_action", "", outil, args)
            resultats.append(str(resultat))
        except TypeError as e:
            message = f"Arguments invalides pour {data.get('outil')} : {e}"
            journaliser_erreur_systeme(
                resultat_erreur(message, categorie="erreur_technique_outil"),
                contexte="mode_action",
                objectif="",
                outil=data.get("outil"),
                args=data.get("args", {}),
                resultat_brut=message,
            )
            resultats.append(message)
        except Exception as e:
            message = f"Erreur outil {data.get('outil')} : {e}"
            journaliser_erreur_systeme(
                resultat_erreur(message, e),
                contexte="mode_action",
                objectif="",
                outil=data.get("outil"),
                args=data.get("args", {}),
                resultat_brut=message,
            )
            resultats.append(message)
    return "\n".join(resultats) if resultats else None


def reponse_termine_tache(reponse: str) -> bool:
    return any(objet.get("outil") == "terminer_tache" for objet in extraire_json_objets(reponse))


def resultat_indique_erreur(resultat: str) -> bool:
    marqueurs = ["Erreur", "Outil inconnu", "Arguments invalides", "Timeout"]
    return any(marqueur in resultat for marqueur in marqueurs)


def resultat_est_erreur(resultat) -> bool:
    return bool(getattr(resultat, "erreur", False)) or resultat_indique_erreur(str(resultat))


def _journaliser_resultat_si_erreur(resultat, contexte: str, objectif: str, outil: str, args: dict) -> None:
    if not resultat_est_erreur(resultat):
        return
    journaliser_erreur_systeme(
        resultat,
        contexte=contexte,
        objectif=objectif,
        outil=outil,
        args=args,
        resultat_brut=str(resultat),
    )


def _est_reponse_affirmative(message: str) -> bool:
    return message.strip().lower() in {"oui", "o", "yes", "y", "affiche", "montre", "details", "détails"}


def _est_acknowledgment_contextuel(message: str, historique: list) -> bool:
    """
    Détection déterministe d'acquittements contextuels (NO additional LLM calls).
    
    Returns True if message is a simple acknowledgment following an action.
    Uses pure rule-based classification, never LLM calls.
    """
    message_lower = message.lower().strip()
    
    # Check if message contains acknowledgment words
    est_acquittement = any(mot in message_lower for mot in MOTS_ACQUITTEMENT)
    if not est_acquittement:
        return False
    
    # Check if previous message was an action (context-aware)
    if len(historique) < 2:
        return False
    
    dernier_user = None
    for msg in reversed(historique[:-1]):  # Skip system message, look at user messages
        if msg.get("role") == "user":
            dernier_user = msg.get("content", "")
            break
    
    if not dernier_user:
        return False
    
    # Check if previous user message contained action words
    mots_action_dans_precedent = any(
        mot in dernier_user.lower() 
        for mot in MOTS_ACTION + MOTS_VALIDATION
    )
    
    return mots_action_dans_precedent


def _formater_details_stark(actions: list[dict]) -> str:
    if not actions:
        return "Aucun détail Stark disponible."
    lignes = ["Détail brut du dernier Mode Stark :"]
    for index, action in enumerate(actions, start=1):
        lignes.append(f"\n[{index}] {action.get('objectif', '?')} :: {action.get('outil')}({action.get('args', {})})")
        lignes.append(str(action.get("resultat_brut", "")))
    return "\n".join(lignes)


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
# MODE STARK — BOUCLE AGENTIQUE STRUCTUREE
# ============================================================================

@dataclass
class EtatMicroObjectif:
    objectif: str
    decisions_utilisees: int = 0
    actions: list[dict] = field(default_factory=list)
    derniere_action: dict | None = None
    termine: bool = False
    resultat_final: str | None = None
    statut_erreur_technique: bool = False
    echecs_consecutifs: int = 0
    echecs_recherche_web: int = 0  # Compteur spécifique pour les échecs de recherche web


def executer_mode_stark(objectif: str, historique: list, memoire: dict) -> str:
    """
    Mode Stark : Jarvis orchestre une structure explicite d'objectifs
    atomiques. Le LLM ne reçoit que le micro-objectif courant et un résumé
    compact de ses tentatives précédentes.
    """
    global DERNIERS_DETAILS_STARK, ATTENTE_DETAILS_STARK
    instances = verifier_instances_stark()
    if instances:
        lignes = [
            f"{len(instances)} instance(s) Stark deja active(s) :",
            *[
                f"- PID {i.get('pid')} ({i.get('nom_process', '?')}) depuis {i.get('lance_le', '?')} : {i.get('objectif', '')}"
                for i in instances
            ],
        ]
        if not demander_confirmation("\n".join(lignes) + "\nLancer une nouvelle instance Stark malgre tout ?"):
            return "Mode Stark annule : une autre instance est deja active."

    plan = parser_objectif_stark(objectif)

    enregistrer_instance_stark(objectif)
    activer_mode_stark()
    console.print(Panel(f"Objectif : {escape(objectif)}", title="⚡ Mode Stark activé", style="bold red"))
    event_bus.emit("stark_activated", {"objectif": objectif})

    rapports_segments = [
        {
            "index": segment.index,
            "texte": segment.texte,
            "statut": "jamais tenté",
            "details": [],
        }
        for segment in plan.segments
    ]

    try:
        chaine_interrompue = False
        contexte_global_segments = []
        for segment, rapport_segment in zip(plan.segments, rapports_segments):
            if chaine_interrompue:
                rapport_segment["statut"] = "jamais tenté à cause d'une dépendance non satisfaite"
                continue

            succes_segment = _executer_segment_stark(
                segment,
                historique,
                memoire,
                rapport_segment,
                contexte_precedent=contexte_global_segments,
            )
            if succes_segment:
                rapport_segment["statut"] = "réussi"
                # Synthèse du résultat pour le contexte des étapes suivantes
                resume_segment = "Segment validé avec succès."
                for detail in rapport_segment.get("details", []):
                    for alt in detail.get("alternatives", []):
                        if alt.get("statut") == "réussi" and alt.get("resume"):
                            resume_segment = alt.get("resume")
                contexte_global_segments.append({
                    "index": segment.index,
                    "texte": segment.texte,
                    "statut": "réussi",
                    "resume": resume_segment,
                })
            else:
                if any(detail.get("statut") == "erreur_technique" for detail in rapport_segment["details"]):
                    rapport_segment["statut"] = "erreur_technique"
                elif any(detail.get("statut") == "echecs_consecutifs" for detail in rapport_segment["details"]):
                    rapport_segment["statut"] = "echecs_consecutifs"
                else:
                    rapport_segment["statut"] = "échoué"
                chaine_interrompue = True

        DERNIERS_DETAILS_STARK = _extraire_actions_brutes_rapport(rapports_segments)
        ATTENTE_DETAILS_STARK = bool(DERNIERS_DETAILS_STARK)
        rapport = _formater_rapport_stark(objectif, rapports_segments)
        if ATTENTE_DETAILS_STARK:
            rapport += "\n\nSouhaitez-vous voir le détail brut des résultats du Mode Stark ?"
        titre = "⚡ Mode Stark — terminé" if not chaine_interrompue else "⚡ Mode Stark — interrompu"
        style = "bold green" if not chaine_interrompue else "bold yellow"
        console.print(Panel(escape(rapport), title=titre, style=style))
        event_bus.emit(
            "stark_terminated",
            {
                "statut": "interrompu" if chaine_interrompue else "terminé",
                "rapport": rapport,
            },
        )
        return rapport
    finally:
        retirer_instance_stark()
        desactiver_mode_stark()


def _executer_segment_stark(
    segment: StarkSegment,
    historique: list,
    memoire: dict,
    rapport_segment: dict,
    contexte_precedent: list[dict] | None = None,
) -> bool:
    for position, branche in enumerate(segment.branches, start=1):
        succes_branche = False
        erreur_technique = False
        echecs_consecutifs = False
        details_alternatives = []
        for alternative in branche.actions:
            resultat = _executer_micro_objectif_stark(
                alternative,
                historique,
                memoire,
                contexte_precedent=contexte_precedent,
            )
            details_alternatives.append(resultat)
            if resultat["statut"] == "réussi":
                succes_branche = True
                break
            if resultat["statut"] == "erreur_technique":
                erreur_technique = True
                break
            if resultat["statut"] == "echecs_consecutifs":
                echecs_consecutifs = True
                break

        rapport_segment["details"].append({
            "branche": position,
            "alternatives": details_alternatives,
            "statut": "réussi" if succes_branche else (
                "erreur_technique" if erreur_technique else (
                    "echecs_consecutifs" if echecs_consecutifs else "échoué"
                )
            ),
        })

        if not succes_branche:
            return False
    return True


def _extraire_actions_brutes_rapport(rapports_segments: list[dict]) -> list[dict]:
    actions = []
    for segment in rapports_segments:
        for detail in segment["details"]:
            for alternative in detail["alternatives"]:
                actions.extend(alternative.get("actions_brutes", []))
    return actions


def _executer_micro_objectif_stark(
    micro_objectif: str,
    historique: list,
    memoire: dict,
    contexte_precedent: list[dict] | None = None,
) -> dict:
    etat = EtatMicroObjectif(objectif=micro_objectif)
    avertissement_repetition = None

    while etat.decisions_utilisees < MAX_ETAPES_PAR_MICRO_OBJECTIF and not etat.termine:
        message_stark = _construire_message_micro_objectif(
            etat,
            avertissement=avertissement_repetition,
            contexte_precedent=contexte_precedent,
        )
        avertissement_repetition = None
        with console.status(
            f"[red]⚡ Stark réfléchit ({etat.decisions_utilisees + 1}/{MAX_ETAPES_PAR_MICRO_OBJECTIF}) : {micro_objectif[:80]}[/red]",
            spinner="dots",
        ):
            event_bus.emit("thinking", {"message": "Jarvis réfléchit..."})
            resultat = interpreter_objectif(
                message_stark,
                historique,
                memoire,
                temperature=0.3,
                mode_stark=True,
                on_event=event_bus.emit,
            )

        if resultat.get("raisonnement"):
            console.print(f"[dim italic red]⚡ Raisonnement : {resultat['raisonnement']}[/dim italic red]")

        etat.decisions_utilisees += 1

        actions = resultat.get("actions", [])
        if not actions:
            break

        action = actions[0]
        repetition = _message_repetition_action(etat, action)
        if repetition:
            avertissement_repetition = repetition
            continue

        _executer_action_stark(action, etat)
        if etat.statut_erreur_technique:
            return {
                "objectif": micro_objectif,
                "statut": "erreur_technique",
                "resume": etat.resultat_final or "Erreur technique pendant l'appel d'outil.",
                "tentatives": _actions_vers_tentatives(etat),
                "actions_brutes": _actions_brutes(etat),
            }
        if etat.echecs_consecutifs >= SEUIL_ECHECS_CONSECUTIFS_STARK:
            return {
                "objectif": micro_objectif,
                "statut": "echecs_consecutifs",
                "resume": "3 échecs consécutifs, abandon pour éviter de gaspiller le budget restant.",
                "tentatives": _actions_vers_tentatives(etat),
                "actions_brutes": _actions_brutes(etat),
            }

    if etat.termine:
        return {
            "objectif": micro_objectif,
            "statut": "réussi",
            "resume": etat.resultat_final or "Objectif atteint.",
            "tentatives": _actions_vers_tentatives(etat),
            "actions_brutes": _actions_brutes(etat),
        }

    return {
        "objectif": micro_objectif,
        "statut": "échoué",
        "resume": f"Budget de {MAX_ETAPES_PAR_MICRO_OBJECTIF} décisions épuisé." if etat.decisions_utilisees >= MAX_ETAPES_PAR_MICRO_OBJECTIF else "Aucune action proposée par Core Intellect.",
        "tentatives": _actions_vers_tentatives(etat),
        "actions_brutes": _actions_brutes(etat),
    }


def _message_repetition_action(etat: EtatMicroObjectif, action: dict) -> str | None:
    outil = action.get("outil")
    args = action.get("args", {})
    if outil == "terminer_tache":
        return None
    action_courante = {"outil": outil, "args": args}
    if etat.derniere_action != action_courante:
        return None
    dernier_resultat = etat.actions[-1]["resultat_brut"] if etat.actions else ""
    return (
        "Action déjà exécutée à l'instant avec ces arguments exacts. "
        f"Résultat obtenu :\n{dernier_resultat}\n\n"
        "Propose une action différente ou appelle terminer_tache si l'objectif est atteint."
    )


def _executer_action_stark(action: dict, etat: EtatMicroObjectif) -> None:
    outil = action.get("outil")
    args = action.get("args", {})

    if outil == "terminer_tache":
        etat.termine = True
        etat.resultat_final = args.get("resume", "Objectif atteint.")
        etat.actions.append({
            "outil": outil,
            "args": args,
            "resultat_brut": etat.resultat_final,
            "erreur": False,
        })
        event_bus.emit(
            "stark_action",
            {
                "outil": outil,
                "args": args,
                "resultat": etat.resultat_final,
                "erreur": False,
            },
        )
        return

    if outil not in OUTILS:
        resultat_outil = f"Outil inconnu : {outil}"
        etat.actions.append({
            "outil": outil,
            "args": args,
            "resultat_brut": resultat_outil,
            "erreur": True,
        })
        console.print(f"[yellow]⚡ Outil inconnu ignoré : {outil}[/yellow]")
        event_bus.emit(
            "stark_action",
            {
                "outil": outil,
                "args": args,
                "resultat": resultat_outil,
                "erreur": True,
            },
        )
        return

    event_bus.emit("tool_started", {"outil": outil, "args": args, "mode": "stark"})
    try:
        resultat_outil = OUTILS[outil](**args)
        resultat_texte = str(resultat_outil)
        entree = {
            "outil": outil,
            "args": args,
            "resultat_brut": resultat_texte,
            "erreur": resultat_est_erreur(resultat_outil),
            "categorie_erreur": getattr(resultat_outil, "categorie_erreur", None),
            "code_brut": getattr(resultat_outil, "code_brut", None),
        }
        etat.actions.append(entree)
        etat.derniere_action = {"outil": outil, "args": args}
        if entree["erreur"]:
            etat.echecs_consecutifs += 1
            
            # Détection spécifique pour les échecs de recherche web
            if outil in ["rechercher_web", "rechercher_et_analyser", "analyser_page_web"]:
                etat.echecs_recherche_web += 1
                if etat.echecs_recherche_web >= SEUIL_ECHECS_RECHERCHE_WEB:
                    console.print(f"[yellow]⚡ Seuil d'échecs recherche web atteint ({SEUIL_ECHECS_RECHERCHE_WEB}), abandon de la recherche[/yellow]")
                    etat.resultat_final = f"Échec de la recherche web après {SEUIL_ECHECS_RECHERCHE_WEB} tentatives. Veuillez reformuler votre demande ou vérifier votre connexion internet."
                    etat.termine = True
            
            _journaliser_resultat_si_erreur(resultat_outil, "mode_stark", etat.objectif, outil, args)
        else:
            etat.echecs_consecutifs = 0
            # Réinitialiser le compteur de recherche web en cas de succès
            if outil in ["rechercher_web", "rechercher_et_analyser", "analyser_page_web"]:
                etat.echecs_recherche_web = 0
        event_bus.emit(
            "tool_failed" if entree["erreur"] else "tool_completed",
            {
                "outil": outil,
                "args": args,
                "resultat": resultat_texte,
                "mode": "stark",
            },
        )
        console.print(f"[dim red]⚡ {outil} -> {resultat_texte[:120]}[/dim red]")
        event_bus.emit(
            "stark_action",
            {
                "outil": outil,
                "args": args,
                "resultat": resultat_texte,
                "erreur": entree["erreur"],
            },
        )
    except TypeError as e:
        erreur = f"ERREUR TECHNIQUE arguments {outil} : {e}"
        etat.actions.append({
            "outil": outil,
            "args": args,
            "resultat_brut": erreur,
            "erreur": True,
            "categorie_erreur": "erreur_technique_outil",
            "code_brut": None,
        })
        etat.statut_erreur_technique = True
        etat.resultat_final = erreur
        journaliser_erreur_systeme(
            resultat_erreur(erreur, categorie="erreur_technique_outil"),
            contexte="mode_stark",
            objectif=etat.objectif,
            outil=outil,
            args=args,
            resultat_brut=erreur,
        )
        console.print(f"[red]⚡ Erreur technique arguments {outil} : {e}[/red]")
        event_bus.emit("tool_failed", {"outil": outil, "args": args, "resultat": erreur, "mode": "stark"})
        event_bus.emit(
            "stark_action",
            {
                "outil": outil,
                "args": args,
                "resultat": erreur,
                "erreur": True,
            },
        )
    except Exception as e:
        erreur = f"ERREUR : {e}"
        resultat = resultat_erreur(erreur, e)
        etat.actions.append({
            "outil": outil,
            "args": args,
            "resultat_brut": erreur,
            "erreur": True,
            "categorie_erreur": resultat.categorie_erreur,
            "code_brut": resultat.code_brut,
        })
        etat.derniere_action = {"outil": outil, "args": args}
        etat.echecs_consecutifs += 1
        
        # Détection spécifique pour les échecs de recherche web
        if outil in ["rechercher_web", "rechercher_et_analyser", "analyser_page_web"]:
            etat.echecs_recherche_web += 1
            if etat.echecs_recherche_web >= SEUIL_ECHECS_RECHERCHE_WEB:
                console.print(f"[yellow]⚡ Seuil d'échecs recherche web atteint ({SEUIL_ECHECS_RECHERCHE_WEB}), abandon de la recherche[/yellow]")
                etat.resultat_final = f"Échec de la recherche web après {SEUIL_ECHECS_RECHERCHE_WEB} tentatives. Veuillez reformuler votre demande ou vérifier votre connexion internet."
                etat.termine = True
        
        journaliser_erreur_systeme(
            resultat,
            contexte="mode_stark",
            objectif=etat.objectif,
            outil=outil,
            args=args,
            resultat_brut=erreur,
        )
        console.print(f"[red]⚡ Erreur {outil} : {e}[/red]")
        event_bus.emit("tool_failed", {"outil": outil, "args": args, "resultat": erreur, "mode": "stark"})
        event_bus.emit(
            "stark_action",
            {
                "outil": outil,
                "args": args,
                "resultat": erreur,
                "erreur": True,
            },
        )

def _actions_vers_tentatives(etat: EtatMicroObjectif) -> list[dict]:
    return [
        {
            "numero": index,
            "observation": f"{action['outil']}({action['args']}) -> {action['resultat_brut']}",
        }
        for index, action in enumerate(etat.actions, start=1)
    ]


def _actions_brutes(etat: EtatMicroObjectif) -> list[dict]:
    return [
        {
            "objectif": etat.objectif,
            "outil": action.get("outil"),
            "args": action.get("args", {}),
            "resultat_brut": action.get("resultat_brut", ""),
            "erreur": action.get("erreur", False),
            "categorie_erreur": action.get("categorie_erreur"),
            "code_brut": action.get("code_brut"),
        }
        for action in etat.actions
    ]


def _construire_message_micro_objectif(
    etat: EtatMicroObjectif,
    avertissement: str | None = None,
    contexte_precedent: list[dict] | None = None,
) -> str:
    resume = _formater_etat_micro_objectif(etat)
    bloc_avertissement = f"\n\nAvertissement runtime :\n{avertissement}" if avertissement else ""

    bloc_contexte_precedent = ""
    if contexte_precedent:
        lignes_ctx = []
        for ctx in contexte_precedent:
            statut = ctx.get("statut", "inconnu")
            texte = ctx.get("texte", "")
            resume_ctx = ctx.get("resume", "")
            lignes_ctx.append(f"- Étape {ctx.get('index', '?')} [{statut}] : {texte}\n  Acquis : {resume_ctx}")
        if lignes_ctx:
            bloc_contexte_precedent = f"\n\nContexte et acquis des étapes précédentes de la mission :\n" + "\n".join(lignes_ctx)

    return (
        f"[MODE STARK — PLEIN ACCÈS & RAISONNEMENT RENFORCÉ]\n\n"
        f"Micro-objectif courant :\n{etat.objectif}\n\n"
        f"Décisions utilisées : {etat.decisions_utilisees}/{MAX_ETAPES_PAR_MICRO_OBJECTIF}"
        f"{bloc_contexte_precedent}\n\n"
        f"État mécanique des actions de ce micro-objectif :\n{resume}"
        f"{bloc_avertissement}\n\n"
        "Protocole de décision Stark (Raisonnement structuré requis dans 'raisonnement') :\n"
        "1. DIAGNOSTIC : Analyse le résultat ou l'erreur de l'action précédente par rapport à l'objectif.\n"
        "2. ÉVALUATION D'IMPACT : Vérifie la cohérence des paramètres (chemins, commandes) pour éviter toute erreur machine.\n"
        "3. DÉCISION :\n"
        f"   - Si l'objectif \"{etat.objectif}\" est déjà atteint par l'état actuel : appelle 'terminer_tache' immédiatement avec un résumé clair.\n"
        "   - Si l'objectif n'est pas encore atteint : propose exactement UNE action ciblée pour progresser.\n"
        "   - Si la tentative précédente a produit une erreur : identifie la cause racine et rectifie directement ta commande sans répéter l'erreur."
    )


def _formater_etat_micro_objectif(etat: EtatMicroObjectif) -> str:
    if not etat.actions:
        return "Aucune action exécutée pour ce micro-objectif."

    entrees = [
        _formater_action_etat(index, action)
        for index, action in enumerate(etat.actions, start=1)
    ]
    total = sum(len(entree) for entree in entrees)
    if total <= MAX_CONTEXTE_TENTATIVES_STARK:
        return "\n\n".join(entrees)

    selection = []
    taille = 0
    for entree in reversed(entrees):
        if not selection:
            selection.append(entree)
            taille += len(entree)
            continue
        if taille + len(entree) <= MAX_CONTEXTE_TENTATIVES_STARK:
            selection.append(entree)
            taille += len(entree)
        else:
            break

    inclus = set(selection)
    sortie = []
    for index, entree in enumerate(entrees, start=1):
        if entree in inclus:
            sortie.append(entree)
        else:
            action = etat.actions[index - 1]
            sortie.append(
                f"- action {index} : {action['outil']} exécuté, résultat omis pour longueur, voir etat.actions[{index - 1}]"
            )
    return "\n\n".join(sortie)


def _formater_action_etat(index: int, action: dict) -> str:
    statut = "ERREUR" if action.get("erreur") else "OK"
    return (
        f"- action {index} [{statut}] : {action.get('outil')}({action.get('args', {})})\n"
        f"{action.get('resultat_brut', '')}"
    )


def _executer_actions_stark(actions: list[dict]) -> dict:
    etat = EtatMicroObjectif(objectif="")
    for action in actions:
        _executer_action_stark(action, etat)
        if etat.statut_erreur_technique:
            break
    return {
        "termine": etat.termine,
        "resume_final": etat.resultat_final,
        "resume": _formater_etat_micro_objectif(etat),
        "signature": [
            {
                "outil": action["outil"],
                "args": action["args"],
                "erreur": action["erreur"],
                "resultat": action["resultat_brut"],
                "categorie_erreur": action.get("categorie_erreur"),
                "code_brut": action.get("code_brut"),
            }
            for action in etat.actions
        ],
        "erreur_technique": etat.statut_erreur_technique,
    }


def _formater_rapport_stark(objectif: str, rapports_segments: list[dict]) -> str:
    lignes = [f"Mode Stark terminé.", f"Objectif : {objectif}", "", "Rapport par macro-étape :"]
    for segment in rapports_segments:
        lignes.append(f"{segment['index']}. {segment['statut']} — {segment['texte']}")
        for detail in segment["details"]:
            lignes.append(f"   - branche {detail['branche']} : {detail['statut']}")
            for alternative in detail["alternatives"]:
                lignes.append(
                    f"     * {alternative['statut']} — {alternative['objectif']} : {alternative['resume']}"
                )
    return "\n".join(lignes)


def parler(message: str, historique: list, memoire: dict) -> tuple[str, bool]:
    global mode_action_force, ATTENTE_DETAILS_STARK

    # ── Gestion commandes de mode ─────────────────────────────────────────────
    handled_autodestruct, reponse_autodestruct, action_autodestruct = _gerer_autodestruction(message)
    if handled_autodestruct:
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_autodestruct or ""})
        return reponse_autodestruct or "", action_autodestruct

    if ATTENTE_DETAILS_STARK and _est_reponse_affirmative(message):
        ATTENTE_DETAILS_STARK = False
        reponse_details = _formater_details_stark(DERNIERS_DETAILS_STARK)
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_details})
        return reponse_details, False

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

    # ── Detection deterministe d'acquittements (NO additional LLM calls) ───────
    if _est_acknowledgment_contextuel(message, historique):
        # Context-dependent acknowledgment: brief response if confirming action
        reponse_ack = "Parfait, Sir."
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reponse_ack})
        return reponse_ack, False
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
    resultat_intellect = interpreter_objectif(
        message,
        historique,
        memoire,
        forcer_action=etait_mode_action_force,
        on_event=event_bus.emit,
    )

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
            event_bus.emit("tool_started", {"outil": outil, "args": args, "mode": "normal"})
            try:
                resultat = OUTILS[outil](**args)
                contexte = "mode_action" if etait_mode_action_force else "conversation"
                _journaliser_resultat_si_erreur(resultat, contexte, message, outil, args)
                resultats_outils.append(str(resultat))
                event_bus.emit(
                    "tool_failed" if resultat_est_erreur(resultat) else "tool_completed",
                    {
                        "outil": outil,
                        "args": args,
                        "resultat": str(resultat),
                        "mode": "normal",
                    },
                )
            except TypeError as e:
                erreur = f"Erreur outil {outil} : {e}"
                journaliser_erreur_systeme(
                    resultat_erreur(erreur, categorie="erreur_technique_outil"),
                    contexte="mode_action" if etait_mode_action_force else "conversation",
                    objectif=message,
                    outil=outil,
                    args=args,
                    resultat_brut=erreur,
                )
                resultats_outils.append(erreur)
                event_bus.emit("tool_failed", {"outil": outil, "args": args, "resultat": erreur, "mode": "normal"})
            except Exception as e:
                erreur = f"Erreur outil {outil} : {e}"
                journaliser_erreur_systeme(
                    resultat_erreur(erreur, e),
                    contexte="mode_action" if etait_mode_action_force else "conversation",
                    objectif=message,
                    outil=outil,
                    args=args,
                    resultat_brut=erreur,
                )
                resultats_outils.append(erreur)
                event_bus.emit("tool_failed", {"outil": outil, "args": args, "resultat": erreur, "mode": "normal"})

    if resultats_outils:
        reponse_finale = f"{reponse_naturelle}\n\n" + "\n".join(resultats_outils)
    else:
        reponse_finale = reponse_naturelle

    signalement_erreur = signalement_erreurs_autre_recurrentes()
    if signalement_erreur:
        reponse_finale = f"{reponse_finale}\n\n{signalement_erreur}" if reponse_finale else signalement_erreur

    historique.append({"role": "assistant", "content": reponse_finale})
    limiter_historique(historique)
    return reponse_finale, intention_action


def executer_agent(
    user_input: str,
    historique: list,
    memoire: dict,
) -> tuple[str, bool]:
    """
    Exécute une requête utilisateur. Core Intellect gère la compréhension
    et l'exécution en une seule passe (mode normal/action), ou via la
    boucle Stark (mode !S). Cette fonction sert d'interface pour la
    boucle principale.
    """
    try:
        event_bus.emit("thinking", {"message": "Jarvis réfléchit..."})
        reponse, intention_action = parler(user_input, historique, memoire)
        texte = reponse if isinstance(reponse, str) else str(reponse)
        event_bus.emit(
            "response",
            {
                "text": texte,
                "is_action": bool(intention_action),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            },
        )
        return reponse, intention_action
    except Exception as e:
        event_bus.emit("error", {"message": str(e)})
        raise


def preparer_message_utilisateur(message: str) -> str:
    """Applique les enrichissements d'entrée communs à toutes les surfaces."""
    message = message.strip()
    if any(mot in message.lower() for mot in MOTS_OPTIMISATION):
        return message + PLAN_OPTIMISATION
    return message


def executer_interaction_utilisateur(
    message: str,
    historique: list,
    memoire: dict,
    ignorer_si_occupe: bool = False,
    origine_vocale: bool = False,
) -> tuple[str, bool] | None:
    """Exécute et journalise une interaction, avec TTS réservé aux sources vocales."""
    acquired = INTERACTION_LOCK.acquire(blocking=not ignorer_si_occupe)
    if not acquired:
        return None
    result: tuple[str, bool]
    try:
        message_prepare = preparer_message_utilisateur(message)
        reponse, intention_action = executer_agent(message_prepare, historique, memoire)
        texte = reponse if isinstance(reponse, str) else str(reponse)
        OUTILS["enregistrer_echange"](message_prepare, texte)
        result = texte, intention_action
    finally:
        INTERACTION_LOCK.release()
    if origine_vocale:
        from capabilities.voice_output import parler_a_voix_haute

        parler_a_voix_haute(result[0])
    return result


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
                resultat = self.outils[outil](**args)
                _journaliser_resultat_si_erreur(resultat, "veille", "veille autonome", outil, args)
                resultats.append(str(resultat))
                executed_actions.append(action)
            except TypeError as e:
                erreur = f"Erreur outil {outil} : {e}"
                journaliser_erreur_systeme(
                    resultat_erreur(erreur, categorie="erreur_technique_outil"),
                    contexte="veille",
                    objectif="veille autonome",
                    outil=outil,
                    args=args,
                    resultat_brut=erreur,
                )
                resultats.append(erreur)
            except Exception as e:
                erreur = f"Erreur outil {outil} : {e}"
                journaliser_erreur_systeme(
                    resultat_erreur(erreur, e),
                    contexte="veille",
                    objectif="veille autonome",
                    outil=outil,
                    args=args,
                    resultat_brut=erreur,
                )
                resultats.append(erreur)
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
                            escape("\n".join(meaningful)),
                            title="Jarvis — Action autonome",
                            style="yellow"
                        ))
                    self.notification_results = []
                self.last_observations = etat
            except Exception as e:
                self.console.print(f"[dim yellow]Agent autonome: {e}[/dim yellow]")


def demarrer_agent_autonome(memoire: dict, console_instance: Console | None = None):
    """Démarre la veille autonome utilisée par la console et l'API."""
    stop_event = threading.Event()
    agent = AutonomousAgent(
        memoire=memoire,
        outils=OUTILS,
        console=console_instance or console,
    )
    veille = threading.Thread(target=agent.run, args=(stop_event,), daemon=True)
    veille.start()
    return agent, stop_event, veille


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
    _, stop_event, _ = demarrer_agent_autonome(memoire, console)
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

            horodatage = datetime.now().strftime("%H:%M:%S")
            with console.status("[cyan]Jarvis réfléchit...[/cyan]", spinner="dots"):
                reponse, intention_action = executer_interaction_utilisateur(user_input, historique, memoire)

            reponse = reponse if isinstance(reponse, str) else ""
            console.print(Panel(escape(reponse), title=f"Jarvis — {horodatage}", style="cyan"))

        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break


if __name__ == "__main__":
    main()
