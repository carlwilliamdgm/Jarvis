import json
import os
import threading
from datetime import datetime
from json import JSONDecodeError

from core.paths import MEMORY_PATH

CATEGORIES_CONTEXTE = {"profil", "habitudes", "objectifs", "projets", "faits", "contraintes", "style"}
MAX_JOURNAL_CONVERSATION = 20
MAX_HISTORIQUE_ACTIONS = 100
MAX_TACHES = 50
_MEMORY_LOCK = threading.RLock()


def schema_contexte() -> dict:
    return {categorie: {} for categorie in sorted(CATEGORIES_CONTEXTE)}


def charger_memoire() -> dict:
    with _MEMORY_LOCK:
        try:
            with open(MEMORY_PATH, "r", encoding="utf-8") as f:
                contenu = f.read().strip()
                return json.loads(contenu) if contenu else {}
        except (FileNotFoundError, JSONDecodeError):
            return {}


def sauvegarder_memoire(data: dict):
    with _MEMORY_LOCK:
        tmp_path = MEMORY_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MEMORY_PATH)


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
    contexte = data.setdefault("contexte", schema_contexte())
    for categorie in CATEGORIES_CONTEXTE:
        contexte.setdefault(categorie, {})
    return data


def journaliser_action(outil: str, args: dict, resultat: str) -> None:
    with _MEMORY_LOCK:
        data = normaliser_memoire(charger_memoire())
        historique = data.get("historique_actions", [])
        historique.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "outil": outil,
            "args": args,
            "resultat": resultat[:300],
        })
        data["historique_actions"] = historique[-MAX_HISTORIQUE_ACTIONS:]
        sauvegarder_memoire(data)


def enregistrer_echange(utilisateur: str, jarvis: str) -> str:
    with _MEMORY_LOCK:
        data = normaliser_memoire(charger_memoire())
        journal = data.get("journal_conversation", [])
        journal.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "utilisateur": utilisateur[:500],
            "jarvis": jarvis[:500],
        })
        data["journal_conversation"] = journal[-MAX_JOURNAL_CONVERSATION:]
        sauvegarder_memoire(data)
    return "Echange journalise."


def sauvegarder_session(historique: list) -> None:
    """Sauvegarde les derniers échanges de la session pour reprise."""
    data = normaliser_memoire(charger_memoire())
    data["session_precedente"] = historique[-10:]
    sauvegarder_memoire(data)


def charger_session_precedente() -> list:
    """Récupère les derniers échanges de la session précédente."""
    data = charger_memoire()
    return data.get("session_precedente", [])


def enregistrer_tache(description: str, etat: str = "en_cours", contexte: dict = None) -> int:
    """Enregistre une tâche avec son état pour reprise possible."""
    data = normaliser_memoire(charger_memoire())
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
    sauvegarder_memoire(data)
    return tache_id


def mettre_a_jour_tache(tache_id: int, etat: str, contexte: dict = None) -> None:
    """Met à jour l'état d'une tâche."""
    data = normaliser_memoire(charger_memoire())
    taches = data.get("taches", [])
    for tache in taches:
        if tache.get("id") == tache_id:
            tache["etat"] = etat
            tache["mis_a_jour_le"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if contexte:
                tache["contexte"] = contexte
            break
    data["taches"] = taches
    sauvegarder_memoire(data)


def taches_interrompues() -> list:
    """Retourne les tâches en cours non terminées."""
    data = charger_memoire()
    return [t for t in data.get("taches", []) if t.get("etat") == "en_cours"]
