#core/memory.py

from contextlib import contextmanager
import json
import os
import re
import shutil
import threading
import time
from collections import Counter
from datetime import datetime
from json import JSONDecodeError
from typing import Any

from datashield.error_classification import CATEGORIES_ERREUR, classifier_erreur_systeme, extraire_code_erreur
from core_intellect.paths import MEMORY_PATH
from context_engine.memory_store import get_memory_store
from greatos_contracts import CapabilityResult, CapabilityStatus, PolicyDecision


CATEGORIES_CONTEXTE = {"profil", "habitudes", "objectifs", "projets", "faits", "contraintes", "style"}
MAX_JOURNAL_CONVERSATION = 20
MAX_HISTORIQUE_ACTIONS = 100
MAX_TACHES = 50
MAX_ERREURS_SYSTEME_PAR_CATEGORIE = 100
_MEMORY_LOCK = threading.RLock()


@contextmanager
def transaction_memoire():
    """
    Gestionnaire de contexte transactionnel pour la mémoire.
    Délègue au store actif (SQLite WAL ou JSON).
    Garantit l'atomicité et l'isolation des opérations de lecture-modification-écriture.
    En cas d'exception non gérée dans le bloc, aucune modification n'est persistée (rollback implicite).
    """
    store = get_memory_store()
    with store.transaction() as data:
        yield data


def schema_contexte() -> dict:
    return {categorie: {} for categorie in sorted(CATEGORIES_CONTEXTE)}


def charger_memoire() -> dict:
    store = get_memory_store()
    return store.load()


def sauvegarder_memoire(data: dict):
    store = get_memory_store()
    store.save(data)



def normaliser_memoire(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}
    data.setdefault("notes", [])
    data.setdefault("preferences", {})
    data.setdefault("historique_actions", [])
    data.setdefault("rappels", [])
    data.setdefault("commandes_personnalisees", {})
    data.setdefault("automatisations", [])
    data.setdefault("surveillances_dossiers", [])
    data.setdefault("actions_en_attente", [])
    data.setdefault("journal_conversation", [])
    data.setdefault("signaux_proactifs", {})
    data.setdefault("taches", [])
    data.setdefault("session_precedente", [])
    data.setdefault("signaux_erreurs_autre_notifies", [])
    data.setdefault("patterns_comportementaux", {})
    data.setdefault("feedback_suggestions", [])
    data.setdefault("alerts_systeme", [])
    data.setdefault("historique_systeme", [])
    data.setdefault("evenements_calendrier", [])
    data.setdefault("derniere_sync_calendrier", "")
    data.setdefault("emails_recents", [])
    data.setdefault("derniere_sync_emails", "")
    data.setdefault("apprentissage_succes", [])
    data.setdefault("apprentissages", [])
    data.setdefault("personnalite", {})
    data.setdefault("ajustements_personnalite", [])
    data.setdefault("preferences_communication", {})
    data.setdefault("index_semantique", {})
    data.setdefault("dernier_enrichissement", "")
    contexte = data.setdefault("contexte", schema_contexte())
    for categorie in CATEGORIES_CONTEXTE:
        contexte.setdefault(categorie, {})
    erreurs = data.setdefault("erreurs_systeme", {})
    for categorie in CATEGORIES_ERREUR:
        erreurs.setdefault(categorie, [])
    return data


_MOTS_CLES_SECRETS = {
    "password", "passwd", "mdp", "mot_de_passe",
    "secret", "token", "api_key", "apikey", "key",
    "authorization", "auth", "credential", "credentials",
    "private_key", "bearer", "cookie",
}

_PATTERNS_SECRETS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.DOTALL),
]


def _masquer_texte_sensible(texte: str) -> str:
    if not isinstance(texte, str):
        return texte
    nettoye = texte
    for pattern in _PATTERNS_SECRETS:
        nettoye = pattern.sub("[SECRET_MASQUÉ]", nettoye)
    return nettoye


def filtrer_arguments_sensibles(valeur: Any, profondeur: int = 0) -> Any:
    """Filtre récursivement dictionnaires, listes et chaînes pour éviter d'inscrire des secrets."""
    if profondeur > 10:
        return "[PROFONDEUR_MAX]"
    if isinstance(valeur, dict):
        resultat = {}
        for cle, val in valeur.items():
            cle_str = str(cle).lower()
            if any(mot in cle_str for mot in _MOTS_CLES_SECRETS):
                resultat[cle] = "[MASQUÉ]"
            else:
                resultat[cle] = filtrer_arguments_sensibles(val, profondeur + 1)
        return resultat
    if isinstance(valeur, (list, tuple)):
        return [filtrer_arguments_sensibles(elem, profondeur + 1) for elem in valeur]
    if isinstance(valeur, str):
        valeur_filtree = _masquer_texte_sensible(valeur)
        if len(valeur_filtree) > 500:
            return valeur_filtree[:500] + "... [TRONQUÉ]"
        return valeur_filtree
    return valeur


def journaliser_action(outil: str, args: dict, resultat: str) -> None:
    args_filtres = filtrer_arguments_sensibles(args)
    res_str = _masquer_texte_sensible(str(resultat))[:300]
    with transaction_memoire() as data:
        historique = data.get("historique_actions", [])
        historique.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "outil": outil,
            "args": args_filtres,
            "resultat": res_str,
        })
        data["historique_actions"] = historique[-MAX_HISTORIQUE_ACTIONS:]


def journaliser_resultat_capacite(
    resultat: CapabilityResult,
    arguments: dict | None = None,
    decision: PolicyDecision | dict | str | None = None,
    contexte: str = "",
) -> dict:
    """Journalise de façon souveraine un CapabilityResult dans Context Engine."""
    decision_normalisee: dict[str, str]
    if isinstance(decision, PolicyDecision):
        decision_normalisee = {"decision": decision.decision.value, "reason": decision.reason}
    elif isinstance(decision, dict):
        decision_normalisee = {
            "decision": str(decision.get("decision", "allow")),
            "reason": str(decision.get("reason", "")),
        }
    elif isinstance(decision, str):
        decision_normalisee = {"decision": decision, "reason": ""}
    elif resultat.data.get("security_decision"):
        sec = resultat.data["security_decision"]
        if isinstance(sec, dict):
            decision_normalisee = sec
        else:
            decision_normalisee = {"decision": str(sec), "reason": ""}
    elif (
        resultat.status == CapabilityStatus.DENIED
        or resultat.error_category in {"defcon_blocked", "securite_bloquee"}
    ):
        decision_normalisee = {"decision": "deny", "reason": resultat.message}
    elif (
        resultat.status == CapabilityStatus.CANCELLED
        or resultat.error_category in {"action_refusee_par_confirmation", "confirmation_refusee"}
    ):
        decision_normalisee = {"decision": "confirm", "reason": "action_annulee_ou_refusee"}
    else:
        decision_normalisee = {"decision": "allow", "reason": "autorise"}

    args_filtres = filtrer_arguments_sensibles(arguments or {})
    legacy_tool = str(resultat.data.get("legacy_tool") or resultat.capability)
    owner = str(resultat.data.get("owner") or "")
    duration_ms = resultat.data.get("duration_ms")

    message_filtre = _masquer_texte_sensible(str(resultat.message))
    if len(message_filtre) > 500:
        message_filtre = message_filtre[:500] + "... [TRONQUÉ]"

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entree = {
        "date": date_str,
        "outil": legacy_tool,
        "capability": resultat.capability,
        "owner": owner,
        "status": resultat.status.value if hasattr(resultat.status, "value") else str(resultat.status),
        "args": args_filtres,
        "decision": decision_normalisee,
        "duree_ms": duration_ms,
        "resultat": message_filtre,
        "error_category": resultat.error_category,
        "contexte": contexte,
    }

    with transaction_memoire() as data:
        historique = data.get("historique_actions", [])
        historique.append(entree)
        data["historique_actions"] = historique[-MAX_HISTORIQUE_ACTIONS:]

    return entree


def consulter_trace_capacites(
    limite: int = 50,
    statut: str | None = None,
    proprietaire: str | None = None,
    capacite: str | None = None,
) -> list[dict]:
    """Consulte et filtre les traces des capacités enregistrées dans Context Engine."""
    data = charger_memoire()
    historique = data.get("historique_actions", [])
    resultats = []
    for entree in reversed(historique):
        if statut and entree.get("status") != statut:
            continue
        if proprietaire and entree.get("owner") != proprietaire:
            continue
        if capacite and entree.get("capability") != capacite and entree.get("outil") != capacite:
            continue
        resultats.append(entree)
        if len(resultats) >= limite:
            break
    return resultats



def journaliser_erreur_systeme(
    erreur,
    contexte: str,
    objectif: str,
    outil: str,
    args: dict | None,
    resultat_brut: str,
) -> str:
    categorie = classifier_erreur_systeme(erreur)
    code_brut = extraire_code_erreur(erreur)
    with transaction_memoire() as data:
        erreurs = data["erreurs_systeme"]
        entree = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contexte": contexte,
            "objectif": objectif,
            "outil": outil,
            "args": args or {},
            "code_brut": code_brut,
            "resultat_brut": str(resultat_brut),
        }
        erreurs[categorie].append(entree)
        erreurs[categorie] = erreurs[categorie][-MAX_ERREURS_SYSTEME_PAR_CATEGORIE:]
    return categorie


def signalement_erreurs_autre_recurrentes() -> str | None:
    code = None
    compteur = None
    selection = []
    with transaction_memoire() as data:
        occurrences = data["erreurs_systeme"].get("autre", [])
        codes = [
            entree.get("code_brut")
            for entree in occurrences
            if entree.get("code_brut") is not None
        ]
        compteur = Counter(codes)
        deja_notifies = set(data.get("signaux_erreurs_autre_notifies", []))
        code = next(
            (
                c
                for c, total in sorted(compteur.items(), key=lambda item: (-item[1], str(item[0])))
                if total >= 3 and str(c) not in deja_notifies
            ),
            None,
        )
        if code is not None:
            selection = [entree for entree in occurrences if entree.get("code_brut") == code][-3:]
            data["signaux_erreurs_autre_notifies"].append(str(code))

    if code is None:
        return None

    lignes = [
        f"Code d'erreur système non classifié revenu {compteur[code]} fois : {code}.",
        "Occurrences récentes :",
    ]
    for entree in selection:
        lignes.append(
            f"- {entree.get('date')} | {entree.get('contexte')} | {entree.get('outil')} | {entree.get('resultat_brut')}"
        )
    lignes.append("Souhaitez-vous qu'un développeur crée une catégorie dédiée pour ce code ?")
    return "\n".join(lignes)


def enregistrer_echange(utilisateur: str, jarvis: str) -> str:
    with transaction_memoire() as data:
        journal = data.get("journal_conversation", [])
        journal.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "utilisateur": utilisateur[:500],
            "jarvis": jarvis[:500],
        })
        data["journal_conversation"] = journal[-MAX_JOURNAL_CONVERSATION:]
    return "Echange journalise."


def sauvegarder_session(historique: list) -> None:
    """Sauvegarde les derniers échanges de la session pour reprise."""
    with transaction_memoire() as data:
        data["session_precedente"] = historique[-10:]


def charger_session_precedente() -> list:
    """Récupère les derniers échanges de la session précédente."""
    data = charger_memoire()
    return data.get("session_precedente", [])


def enregistrer_tache(description: str, etat: str = "en_cours", contexte: dict = None) -> int:
    """Enregistre une tâche avec son état pour reprise possible."""
    tache_id = 1
    with transaction_memoire() as data:
        taches = data.get("taches", [])
        tache_id = max([t.get("id", 0) for t in taches], default=0) + 1
        taches.append({
            "id": tache_id,
            "description": description,
            "etat": etat,
            "contexte": contexte or {},
            "cree_le": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mis_a_jour_le": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        data["taches"] = taches[-MAX_TACHES:]
    return tache_id


def mettre_a_jour_tache(tache_id: int, etat: str, contexte: dict = None) -> None:
    """Met à jour l'état d'une tâche."""
    with transaction_memoire() as data:
        taches = data.get("taches", [])
        for tache in taches:
            if tache.get("id") == tache_id:
                tache["etat"] = etat
                tache["mis_a_jour_le"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if contexte:
                    tache["contexte"] = contexte
                break
        data["taches"] = taches


def taches_interrompues() -> list:
    """Retourne les tâches en cours non terminées."""
    data = charger_memoire()
    return [t for t in data.get("taches", []) if t.get("etat") == "en_cours"]