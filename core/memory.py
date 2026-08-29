#core/memory.py

from contextlib import contextmanager
import json
import os
import shutil
import threading
import time
from collections import Counter
from datetime import datetime
from json import JSONDecodeError

from core.error_classification import CATEGORIES_ERREUR, classifier_erreur_systeme, extraire_code_erreur
from core.paths import MEMORY_PATH
from core.memory_store import get_memory_store

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


def journaliser_action(outil: str, args: dict, resultat: str) -> None:
    with transaction_memoire() as data:
        historique = data.get("historique_actions", [])
        historique.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "outil": outil,
            "args": args,
            "resultat": resultat[:300],
        })
        data["historique_actions"] = historique[-MAX_HISTORIQUE_ACTIONS:]


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