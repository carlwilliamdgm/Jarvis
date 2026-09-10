#capabilities/scheduler.py

from datetime import datetime, timedelta

from context_engine.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


FORMAT_DATE_HEURE = "%Y-%m-%d %H:%M"
OUTILS_AUTOMATISATION_INTERDITS = {
    "ajouter_automatisation",
    "ajouter_surveillance_dossier",
    "bilan_proactif",
    "executer_automatisation",
    "executer_automatisations_dues",
    "organiser_dossier",
    "supprimer",
    "vider_corbeille",
}


def parser_moment_rappel(heure: str, maintenant: datetime | None = None) -> datetime | None:
    """Accepte HH:MM ou YYYY-MM-DD HH:MM pour les rappels."""
    maintenant = maintenant or datetime.now()
    texte = str(heure).strip()
    for format_date in (FORMAT_DATE_HEURE, "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(texte, format_date)
        except ValueError:
            pass
    try:
        return datetime.strptime(texte, "%H:%M").replace(
            year=maintenant.year,
            month=maintenant.month,
            day=maintenant.day,
        )
    except ValueError:
        return None


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
        moment = parser_moment_rappel(heure, maintenant)
        if moment is None:
            continue
        if maintenant >= moment:
            rappel["statut"] = "declenche"
            rappel["declenche_le"] = maintenant.strftime(FORMAT_DATE_HEURE)
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
    return cible.strftime(FORMAT_DATE_HEURE)


def ajouter_automatisation(nom: str, outil: str, args: dict | None = None, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    from taskflow.tools import OUTILS

    if outil not in OUTILS:
        return f"Outil inconnu : {outil}"
    if outil in OUTILS_AUTOMATISATION_INTERDITS:
        return f"Outil non automatisable pour eviter un blocage ou une action sensible : {outil}"
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


def executer_action_automatisation(auto: dict, outils: dict, mettre_a_jour_prochaine: bool = False) -> str:
    maintenant = datetime.now()
    outil = auto.get("outil")
    args = auto.get("args", {})
    nom = auto.get("nom", "Automatisation")

    if outil not in outils or outil in {"executer_automatisations_dues", "executer_automatisation"}:
        resultat = f"{nom} : outil indisponible : {outil}"
    else:
        try:
            resultat = f"{nom} : {outils[outil](**args)}"
        except Exception as e:
            resultat = f"{nom} : erreur outil {outil} : {e}"

    auto["derniere_execution"] = maintenant.strftime(FORMAT_DATE_HEURE)
    if mettre_a_jour_prochaine:
        auto["prochaine_execution"] = prochain_declenchement(auto.get("recurrence", "quotidien"), auto.get("heure", "09:00"))
    return resultat


def executer_automatisation(automation_id: int | None = None, nom: str | None = None) -> str:
    """Lance manuellement une automatisation active sans modifier sa prochaine execution planifiee."""
    from taskflow.tools import OUTILS

    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    cible = None
    for auto in automatisations:
        if auto.get("statut") != "active":
            continue
        if automation_id is not None and auto.get("id") == int(automation_id):
            cible = auto
            break
        if nom and auto.get("nom", "").lower() == str(nom).lower():
            cible = auto
            break

    if cible is None:
        return "Automatisation active introuvable."

    resultat = executer_action_automatisation(cible, OUTILS, mettre_a_jour_prochaine=False)
    data = normaliser_memoire(charger_memoire())
    for index, auto in enumerate(data.get("automatisations", [])):
        if auto.get("id") == cible.get("id"):
            data["automatisations"][index] = cible
            break
    sauvegarder_memoire(data)
    return resultat


def executer_automatisations_dues() -> str:
    from taskflow.tools import OUTILS

    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    maintenant = datetime.now()
    resultats = []
    for auto in automatisations:
        if auto.get("statut") != "active":
            continue
        try:
            due = datetime.strptime(auto["prochaine_execution"], FORMAT_DATE_HEURE)
        except (KeyError, ValueError):
            auto["prochaine_execution"] = prochain_declenchement(auto.get("recurrence", "quotidien"), auto.get("heure", "09:00"))
            continue
        if maintenant < due:
            continue
        resultats.append(executer_action_automatisation(auto, OUTILS, mettre_a_jour_prochaine=True))
    data = normaliser_memoire(charger_memoire())
    data["automatisations"] = automatisations
    sauvegarder_memoire(data)
    return "\n\n".join(resultats) if resultats else "Aucune automatisation due."


def proposer_automatisation_auto(outil: str, frequence: int, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    """
    Propose une automatisation basée sur un pattern détecté.
    
    Args:
        outil: L'outil à automatiser
        frequence: La fréquence de détection
        recurrence: La récurrence suggérée (quotidien/hebdomadaire)
        heure: L'heure suggérée
        
    Returns:
        Description de l'automatisation proposée
    """
    from taskflow.tools import OUTILS
    
    if outil not in OUTILS:
        return f"Outil inconnu : {outil}"
    if outil in OUTILS_AUTOMATISATION_INTERDITS:
        return f"Outil non automatisable : {outil}"
    
    nom_suggere = f"Auto_{outil}_{frequence}x"
    
    lignes = [
        f"=== AUTOMATISATION SUGGÉRÉE ===",
        f"Nom : {nom_suggere}",
        f"Outil : {outil}",
        f"Fréquence détectée : {frequence} fois",
        f"Récurrence suggérée : {recurrence}",
        f"Heure suggérée : {heure}",
        "",
        "Pour créer cette automatisation, utilisez :",
        f"ajouter_automatisation(nom=\"{nom_suggere}\", outil=\"{outil}\", recurrence=\"{recurrence}\", heure=\"{heure}\")"
    ]
    
    return "\n".join(lignes)


def creer_automatisation_auto(outil: str, frequence: int, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    """
    Crée automatiquement une automatisation basée sur un pattern détecté.
    
    Args:
        outil: L'outil à automatiser
        frequence: La fréquence de détection
        recurrence: La récurrence suggérée (quotidien/hebdomadaire)
        heure: L'heure suggérée
        
    Returns:
        Résultat de la création de l'automatisation
    """
    from taskflow.tools import OUTILS
    
    if outil not in OUTILS:
        return f"Outil inconnu : {outil}"
    if outil in OUTILS_AUTOMATISATION_INTERDITS:
        return f"Outil non automatisable : {outil}"
    
    nom_auto = f"Auto_{outil}_{frequence}x"
    
    # Vérifier si cette automatisation existe déjà
    data = normaliser_memoire(charger_memoire())
    automatisations = data.get("automatisations", [])
    
    for auto in automatisations:
        if auto.get("outil") == outil and auto.get("statut") == "active":
            return f"Automatisation déjà existante pour {outil} : #{auto['id']} {auto['nom']}"
    
    # Créer l'automatisation
    return ajouter_automatisation(nom=nom_auto, outil=outil, recurrence=recurrence, heure=heure)
