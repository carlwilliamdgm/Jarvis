from datetime import datetime, timedelta

from capabilities.commands import executer_commande_direct
from capabilities.custom_commands import (
    ajouter_commande_personnalisee,
    executer_commande_personnalisee,
    lister_commandes_personnalisees,
)
from capabilities.files import creer_dossier, creer_fichier, lire_fichier, supprimer_direct
from capabilities.memory_tools import (
    lire_contexte,
    lire_notes,
    lire_preferences,
    memoriser_contexte,
    memoriser_preference,
    noter,
    oublier_contexte,
    oublier_preference,
)
from capabilities.organization import analyser_organisation, organiser_dossier_direct
from capabilities.scheduler import (
    ajouter_automatisation,
    ajouter_rappel,
    executer_automatisations_dues,
    lire_rappels,
    lister_automatisations,
    supprimer_rappel,
    verifier_rappels,
)
from capabilities import storage
from capabilities.watchers import (
    ajouter_surveillance_dossier,
    executer_surveillance_dossiers,
    lister_surveillance_dossiers,
    proposer_surveillance_dossiers,
    supprimer_surveillance_dossier,
)
from core.memory import (
    CATEGORIES_CONTEXTE,
    charger_memoire,
    enregistrer_echange,
    journaliser_action,
    normaliser_memoire,
    sauvegarder_memoire,
)
from core.safety import chemin_autorise, racine_trop_large
from rich.console import Console

_console = Console()


def demander_confirmation(description: str) -> bool:
    _console.print(f"\n[yellow]⚠️  Action sensible : {description}[/yellow]")
    choix = _console.input("[bold]Confirmer ? (o/n) >[/bold] ").strip().lower()
    return choix in {"o", "oui", "yes", "y"}


def supprimer(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        if demander_confirmation(f"supprimer {path}"):
            resultat = supprimer_direct(chemin=str(path))
            journaliser_action("supprimer", {"chemin": str(path)}, resultat)
            return resultat
        return "Suppression annulee."
    except Exception as e:
        return f"Erreur : {e}"


def executer_commande(commande: str) -> str:
    return executer_commande_direct(commande=commande)


def vider_temp() -> str:
    return storage.vider_temp()


def vider_corbeille() -> str:
    return storage.vider_corbeille()


def organiser_dossier(chemin: str) -> str:
    try:
        dossier = chemin_autorise(chemin, doit_exister=True)
        if racine_trop_large(dossier):
            return f"Organisation refusee pour une racine trop large : {dossier}."
        plan = analyser_organisation(str(dossier))
        if demander_confirmation(f"organiser {dossier}\n{plan}"):
            resultat = organiser_dossier_direct(chemin=str(dossier))
            journaliser_action("organiser_dossier", {"chemin": str(dossier)}, resultat)
            return resultat
        return "Organisation annulee."
    except Exception as e:
        return f"Erreur : {e}"


def signal_autorise(data: dict, cle: str, delai_minutes: int) -> bool:
    signaux = data.setdefault("signaux_proactifs", {})
    derniere = signaux.get(cle)
    if not derniere:
        signaux[cle] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return True
    try:
        moment = datetime.strptime(derniere, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        signaux[cle] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return True
    if datetime.now() - moment >= timedelta(minutes=delai_minutes):
        signaux[cle] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return True
    return False


def bilan_proactif(force: bool = False, niveau: str = "normal") -> str:
    lignes = []

    rappels = verifier_rappels()
    if not rappels.startswith("Aucun"):
        lignes.append(rappels)

    automatisations = executer_automatisations_dues()
    if not automatisations.startswith("Aucune"):
        lignes.append(automatisations)

    surveillances = executer_surveillance_dossiers(force=False)
    if not surveillances.startswith("Aucune"):
        lignes.append(surveillances)

    data = normaliser_memoire(charger_memoire())

    try:
        libre = storage.get_stockage()
        if libre <= storage.SEUIL_ROUGE and (force or signal_autorise(data, "stockage_rouge", 30)):
            lignes.append(storage.audit_stockage() + "\nSuggestion : preparer un nettoyage avec vider_temp et audit_stockage.")
        elif niveau != "silencieux" and libre <= storage.SEUIL_ORANGE and (force or signal_autorise(data, "stockage_orange", 120)):
            lignes.append(storage.audit_stockage() + "\nSuggestion : surveiller les gros fichiers avec top_fichiers_lourds.")
    except Exception:
        pass

    contexte = data.get("contexte", {})
    if niveau == "complet" and force and not any(contexte.get(cat) for cat in CATEGORIES_CONTEXTE):
        lignes.append("Memoire personnelle peu renseignee.")

    if niveau == "complet" and force and not data.get("automatisations"):
        lignes.append("Aucune automatisation active.")

    if niveau == "complet" and force and not data.get("surveillances_dossiers"):
        lignes.append("Aucune surveillance de dossier active.")

    sauvegarder_memoire(data)
    return "\n\n".join(lignes) if lignes else "Aucun signal proactif pour le moment."


OUTILS = {
    "creer_dossier": creer_dossier,
    "creer_fichier": creer_fichier,
    "lire_fichier": lire_fichier,
    "supprimer": supprimer,
    "noter": noter,
    "lire_notes": lire_notes,
    "memoriser_contexte": memoriser_contexte,
    "lire_contexte": lire_contexte,
    "oublier_contexte": oublier_contexte,
    "enregistrer_echange": enregistrer_echange,
    "audit_stockage": storage.audit_stockage,
    "top_fichiers_lourds": storage.top_fichiers_lourds,
    "vider_temp": vider_temp,
    "vider_corbeille": vider_corbeille,
    "executer_commande": executer_commande,
    "analyser_organisation": analyser_organisation,
    "organiser_dossier": organiser_dossier,
    "ajouter_rappel": ajouter_rappel,
    "lire_rappels": lire_rappels,
    "supprimer_rappel": supprimer_rappel,
    "verifier_rappels": verifier_rappels,
    "memoriser_preference": memoriser_preference,
    "lire_preferences": lire_preferences,
    "oublier_preference": oublier_preference,
    "ajouter_commande_personnalisee": ajouter_commande_personnalisee,
    "lister_commandes_personnalisees": lister_commandes_personnalisees,
    "executer_commande_personnalisee": executer_commande_personnalisee,
    "ajouter_automatisation": ajouter_automatisation,
    "lister_automatisations": lister_automatisations,
    "executer_automatisations_dues": executer_automatisations_dues,
    "proposer_surveillance_dossiers": proposer_surveillance_dossiers,
    "ajouter_surveillance_dossier": ajouter_surveillance_dossier,
    "lister_surveillance_dossiers": lister_surveillance_dossiers,
    "executer_surveillance_dossiers": executer_surveillance_dossiers,
    "supprimer_surveillance_dossier": supprimer_surveillance_dossier,
    "bilan_proactif": bilan_proactif,
}