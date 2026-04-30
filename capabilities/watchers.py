from datetime import datetime, timedelta
from pathlib import Path

from capabilities.organization import analyser_organisation
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.paths import HOME
from core.safety import chemin_autorise, racine_trop_large


def proposer_surveillance_dossiers() -> str:
    candidats = [
        HOME / "Downloads",
        HOME / "Desktop",
        HOME / "Documents",
    ]
    lignes = ["Dossiers pertinents pour une organisation proactive :"]
    for dossier in candidats:
        if not dossier.exists() or not dossier.is_dir():
            continue
        fichiers = sum(1 for item in dossier.iterdir() if item.is_file())
        sous_dossiers = sum(1 for item in dossier.iterdir() if item.is_dir())
        lignes.append(f"- {dossier} : {fichiers} fichier(s), {sous_dossiers} dossier(s)")
    lignes.append("Pour activer : ajouter_surveillance_dossier(chemin, recurrence, heure)")
    return "\n".join(lignes)


def prochain_declenchement(recurrence: str, heure: str) -> str:
    maintenant = datetime.now()
    try:
        cible = datetime.strptime(heure, "%H:%M").replace(
            year=maintenant.year,
            month=maintenant.month,
            day=maintenant.day,
        )
    except ValueError:
        cible = maintenant + timedelta(days=1)

    if cible <= maintenant:
        cible += timedelta(days=1 if recurrence == "quotidien" else 7)
    return cible.strftime("%Y-%m-%d %H:%M")


def ajouter_surveillance_dossier(chemin: str, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    if recurrence not in {"quotidien", "hebdomadaire"}:
        return "Recurrence invalide. Utilisez quotidien ou hebdomadaire."
    try:
        dossier = chemin_autorise(chemin, doit_exister=True)
    except Exception as e:
        return f"Erreur : {e}"
    if not dossier.is_dir():
        return f"Ce chemin n'est pas un dossier : {dossier}"
    if racine_trop_large(dossier):
        return f"Surveillance refusee pour une racine trop large : {dossier}. Ciblez un sous-dossier precis."

    data = normaliser_memoire(charger_memoire())
    surveillances = data.setdefault("surveillances_dossiers", [])
    watcher_id = max([w.get("id", 0) for w in surveillances], default=0) + 1
    surveillances.append({
        "id": watcher_id,
        "chemin": str(dossier),
        "recurrence": recurrence,
        "heure": heure,
        "statut": "active",
        "prochaine_execution": prochain_declenchement(recurrence, heure),
        "cree_le": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    sauvegarder_memoire(data)
    return f"Surveillance #{watcher_id} activee pour {dossier} ({recurrence} a {heure})."


def lister_surveillance_dossiers() -> str:
    data = normaliser_memoire(charger_memoire())
    surveillances = data.get("surveillances_dossiers", [])
    if not surveillances:
        return "Aucune surveillance de dossier active."
    lignes = []
    for watcher in surveillances:
        lignes.append(
            f"#{watcher['id']} {watcher['chemin']} - {watcher['recurrence']} a {watcher['heure']} "
            f"- prochaine: {watcher.get('prochaine_execution', 'inconnue')} - {watcher.get('statut', 'inconnu')}"
        )
    return "\n".join(lignes)


def executer_surveillance_dossiers(force: bool = False) -> str:
    data = normaliser_memoire(charger_memoire())
    surveillances = data.get("surveillances_dossiers", [])
    maintenant = datetime.now()
    resultats = []
    for watcher in surveillances:
        if watcher.get("statut") != "active":
            continue
        try:
            due = datetime.strptime(watcher["prochaine_execution"], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            watcher["prochaine_execution"] = prochain_declenchement(watcher.get("recurrence", "quotidien"), watcher.get("heure", "09:00"))
            continue
        if not force and maintenant < due:
            continue
        chemin = watcher.get("chemin")
        plan = analyser_organisation(chemin)
        if not plan.startswith("Aucun fichier"):
            resultats.append(f"Surveillance #{watcher['id']} - {chemin}\n{plan}")
        watcher["derniere_execution"] = maintenant.strftime("%Y-%m-%d %H:%M")
        watcher["prochaine_execution"] = prochain_declenchement(watcher.get("recurrence", "quotidien"), watcher.get("heure", "09:00"))
    data["surveillances_dossiers"] = surveillances
    sauvegarder_memoire(data)
    return "\n\n".join(resultats) if resultats else "Aucune surveillance de dossier due."


def supprimer_surveillance_dossier(watcher_id: int) -> str:
    data = normaliser_memoire(charger_memoire())
    surveillances = data.get("surveillances_dossiers", [])
    avant = len(surveillances)
    surveillances = [w for w in surveillances if w.get("id") != int(watcher_id)]
    data["surveillances_dossiers"] = surveillances
    sauvegarder_memoire(data)
    return f"Surveillance #{watcher_id} supprimee." if len(surveillances) < avant else f"Surveillance #{watcher_id} introuvable."
