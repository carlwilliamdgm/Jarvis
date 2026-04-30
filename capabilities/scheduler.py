from datetime import datetime, timedelta

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def ajouter_rappel(message: str, heure: str) -> str:
    data = normaliser_memoire(charger_memoire())
    rappels = data.get("rappels", [])
    rappel_id = max([r.get("id", 0) for r in rappels], default=0) + 1
    rappels.append({
        "id": rappel_id,
        "heure": heure,
        "message": message,
        "statut": "en attente",
        "cree_le": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    data["rappels"] = rappels
    sauvegarder_memoire(data)
    return f"Rappel #{rappel_id} cree - {heure} : {message}"


def lire_rappels() -> str:
    data = normaliser_memoire(charger_memoire())
    rappels = data.get("rappels", [])
    if not rappels:
        return "Aucun rappel enregistre."
    lignes = []
    for r in rappels:
        statut = "OK" if r.get("statut") in {"declenche", "déclenché"} else "ATTENTE"
        lignes.append(f"{statut} #{r['id']} - {r['heure']} : {r['message']}")
    return "\n".join(lignes)


def supprimer_rappel(rappel_id: int) -> str:
    data = normaliser_memoire(charger_memoire())
    rappels = data.get("rappels", [])
    avant = len(rappels)
    rappels = [r for r in rappels if r["id"] != int(rappel_id)]
    data["rappels"] = rappels
    sauvegarder_memoire(data)
    return f"Rappel #{rappel_id} supprime." if len(rappels) < avant else f"Rappel #{rappel_id} introuvable."


def verifier_rappels() -> str:
    data = normaliser_memoire(charger_memoire())
    rappels = data.get("rappels", [])
    maintenant = datetime.now()
    declenches = []
    for rappel in rappels:
        if rappel.get("statut") in {"declenche", "déclenché"}:
            continue
        heure = rappel.get("heure", "")
        try:
            moment = datetime.strptime(heure, "%H:%M").replace(
                year=maintenant.year,
                month=maintenant.month,
                day=maintenant.day,
            )
        except ValueError:
            continue
        if maintenant >= moment:
            rappel["statut"] = "declenche"
            rappel["declenche_le"] = maintenant.strftime("%Y-%m-%d %H:%M")
            declenches.append(f"Rappel #{rappel['id']} : {rappel['message']}")
    data["rappels"] = rappels
    if declenches:
        sauvegarder_memoire(data)
        return "\n".join(declenches)
    return "Aucun rappel du."


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


def ajouter_automatisation(nom: str, outil: str, args: dict | None = None, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    from tools import OUTILS

    if outil not in OUTILS:
        return f"Outil inconnu : {outil}"
    if recurrence not in {"quotidien", "hebdomadaire"}:
        return "Recurrence invalide. Utilisez quotidien ou hebdomadaire."

    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    automation_id = max([a.get("id", 0) for a in automatisations], default=0) + 1
    automatisations.append({
        "id": automation_id,
        "nom": nom,
        "outil": outil,
        "args": args or {},
        "recurrence": recurrence,
        "heure": heure,
        "prochaine_execution": prochain_declenchement(recurrence, heure),
        "statut": "active",
    })
    data["automatisations"] = automatisations
    sauvegarder_memoire(data)
    return f"Automatisation #{automation_id} creee : {nom}"


def lister_automatisations() -> str:
    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    if not automatisations:
        return "Aucune automatisation enregistree."
    lignes = []
    for auto in automatisations:
        lignes.append(
            f"#{auto['id']} {auto['nom']} - {auto['outil']} - {auto['recurrence']} "
            f"a {auto['heure']} - prochaine: {auto.get('prochaine_execution', 'inconnue')}"
        )
    return "\n".join(lignes)


def executer_automatisations_dues() -> str:
    from tools import OUTILS

    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    maintenant = datetime.now()
    resultats = []
    for auto in automatisations:
        if auto.get("statut") != "active":
            continue
        try:
            due = datetime.strptime(auto["prochaine_execution"], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            auto["prochaine_execution"] = prochain_declenchement(auto.get("recurrence", "quotidien"), auto.get("heure", "09:00"))
            continue
        if maintenant < due:
            continue
        outil = auto.get("outil")
        args = auto.get("args", {})
        if outil in OUTILS and outil != "executer_automatisations_dues":
            resultats.append(f"{auto['nom']} : {OUTILS[outil](**args)}")
        auto["derniere_execution"] = maintenant.strftime("%Y-%m-%d %H:%M")
        auto["prochaine_execution"] = prochain_declenchement(auto.get("recurrence", "quotidien"), auto.get("heure", "09:00"))
    data["automatisations"] = automatisations
    sauvegarder_memoire(data)
    return "\n\n".join(resultats) if resultats else "Aucune automatisation due."

