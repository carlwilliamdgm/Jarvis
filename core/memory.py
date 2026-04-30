import json
import os
from datetime import datetime
from json import JSONDecodeError

from core.paths import MEMORY_PATH

CATEGORIES_CONTEXTE = {"profil", "habitudes", "objectifs", "projets", "faits", "contraintes", "style"}


def schema_contexte() -> dict:
    return {categorie: {} for categorie in sorted(CATEGORIES_CONTEXTE)}


def charger_memoire() -> dict:
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            contenu = f.read().strip()
            return json.loads(contenu) if contenu else {}
    except (FileNotFoundError, JSONDecodeError):
        return {}


def sauvegarder_memoire(data: dict):
    tmp_path = MEMORY_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, MEMORY_PATH)


def normaliser_memoire(data: dict) -> dict:
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
    contexte = data.setdefault("contexte", schema_contexte())
    for categorie in CATEGORIES_CONTEXTE:
        contexte.setdefault(categorie, {})
    return data


def journaliser_action(outil: str, args: dict, resultat: str) -> None:
    data = normaliser_memoire(charger_memoire())
    historique = data.get("historique_actions", [])
    historique.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "outil": outil,
        "args": args,
        "resultat": resultat[:500],
    })
    data["historique_actions"] = historique[-200:]
    sauvegarder_memoire(data)


def enregistrer_echange(utilisateur: str, jarvis: str) -> str:
    data = normaliser_memoire(charger_memoire())
    journal = data.get("journal_conversation", [])
    journal.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "utilisateur": utilisateur[:1000],
        "jarvis": jarvis[:1000],
    })
    data["journal_conversation"] = journal[-100:]
    sauvegarder_memoire(data)
    return "Echange journalise."
