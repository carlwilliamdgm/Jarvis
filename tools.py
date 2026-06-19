#tools.py

from datetime import datetime, timedelta

from capabilities.commands import executer_commande_direct, executer_powershell_direct
from capabilities.custom_commands import (
    ajouter_commande_personnalisee,
    executer_commande_personnalisee,
    lister_commandes_personnalisees,
)
from capabilities.files import (
    creer_dossier as creer_dossier_direct,
    creer_fichier as creer_fichier_direct,
    lire_fichier,
    lister_dossier,
    supprimer_direct,
)
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
    OUTILS_AUTOMATISATION_INTERDITS,
    ajouter_automatisation,
    ajouter_rappel,
    executer_automatisation,
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
from core.safety import action_requiert_confirmation, chemin_autorise, est_mode_stark_actif
from core.translator import lire_traducteur, obtenir_stats_traducteur
from rich.console import Console

_console = Console()


def demander_confirmation(description: str) -> bool:
    if est_mode_stark_actif():
        return True
    _console.print(f"\n[yellow]⚠️  Action sensible : {description}[/yellow]")
    choix = _console.input("[bold]Confirmer ? (o/n) >[/bold] ").strip().lower()
    return choix in {"o", "oui", "yes", "y"}


def confirmer_ecriture_si_requise(path, description: str) -> bool:
    if not action_requiert_confirmation(path):
        return True
    return demander_confirmation(description)


def creer_dossier(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin)
        if not confirmer_ecriture_si_requise(path, f"creer le dossier {path}"):
            return "Creation de dossier annulee."
        return creer_dossier_direct(chemin=str(path))
    except Exception as e:
        return f"Erreur : {e}"


def creer_fichier(chemin: str, contenu: str = "") -> str:
    try:
        path = chemin_autorise(chemin)
        if not confirmer_ecriture_si_requise(path, f"creer le fichier {path}"):
            return "Creation de fichier annulee."
        return creer_fichier_direct(chemin=str(path), contenu=contenu)
    except Exception as e:
        return f"Erreur : {e}"


def supprimer(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        if not confirmer_ecriture_si_requise(path, f"supprimer {path}"):
            return "Suppression annulee."
        return supprimer_direct(chemin=str(path))
    except Exception as e:
        return f"Erreur : {e}"


def executer_commande(commande: str) -> str:
    return executer_commande_direct(commande=commande)


def executer_powershell(commande: str) -> str:
    return executer_powershell_direct(commande=commande)


def vider_temp() -> str:
    return storage.vider_temp()


def vider_corbeille() -> str:
    return storage.vider_corbeille()


def notifier_utilisateur(titre: str, message: str, urgence: bool = False) -> str:
    storage.notifier(titre=titre, message=message, urgence=urgence)
    return f"Notification envoyee : {titre} - {message}"


def terminer_tache(resume: str = "Tache terminee.") -> str:
    return resume


def ajouter_automatisation_tool(
    nom: str,
    outil: str,
    args: dict | None = None,
    recurrence: str = "quotidien",
    heure: str = "09:00",
) -> str:
    if outil in OUTILS_AUTOMATISATION_INTERDITS:
        return f"Outil non automatisable pour eviter un blocage ou une action sensible : {outil}"
    return ajouter_automatisation(nom=nom, outil=outil, args=args, recurrence=recurrence, heure=heure)


def ajouter_surveillance_dossier_tool(chemin: str, recurrence: str = "quotidien", heure: str = "09:00") -> str:
    return ajouter_surveillance_dossier(chemin=chemin, recurrence=recurrence, heure=heure)


def organiser_dossier(chemin: str) -> str:
    try:
        dossier = chemin_autorise(chemin, doit_exister=True)
        plan = analyser_organisation(str(dossier))
        if not confirmer_ecriture_si_requise(dossier, f"organiser {dossier}\n{plan}"):
            return "Organisation annulee."
        resultat = organiser_dossier_direct(chemin=str(dossier))
        journaliser_action("organiser_dossier", {"chemin": str(dossier)}, f"{plan}\n{resultat}")
        return resultat
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


def lire_traducteur_tool() -> str:
    """Lit le traducteur complet pour consultation libre."""
    traducteur = lire_traducteur()
    stats = obtenir_stats_traducteur()
    
    lignes = [
        f"=== TRADUCTEUR JARVIS ===",
        f"Entrées totales : {stats['total_entrees']}",
        f"Patterns FR : {stats['total_patterns_fr']}",
        f"Patterns EN : {stats['total_patterns_en']}",
        f"Avec intention : {stats['entrees_avec_intention']}",
        f"Sans intention : {stats['entrees_sans_intention']}",
        "",
        "=== ENTRÉES ==="
    ]
    
    for cle, data in sorted(traducteur.items()):
        patterns_fr = ", ".join(data.get("fr", [])[:5])
        patterns_en = ", ".join(data.get("en", [])[:5])
        a_intention = "OUI" if data.get("intention") else "NON"
        
        lignes.append(f"\n[{cle}]")
        lignes.append(f"  FR: {patterns_fr}...")
        lignes.append(f"  EN: {patterns_en}...")
        lignes.append(f"  Intention: {a_intention}")
    
    return "\n".join(lignes)


def modifier_traducteur(cle: str, patterns_fr: str, patterns_en: str, outil: str = "", args_json: str = "{}") -> str:
    """
    Modifie ou ajoute une entrée au traducteur.
    
    Confirmation Carl-William OBLIGATOIRE avant écriture.
    """
    # Demander confirmation
    _console.print(f"\n[yellow]⚠️  Modification du traducteur demandée[/yellow]")
    _console.print(f"[cyan]Clé : {cle}[/cyan]")
    _console.print(f"[cyan]Patterns FR : {patterns_fr}[/cyan]")
    _console.print(f"[cyan]Patterns EN : {patterns_en}[/cyan]")
    if outil:
        _console.print(f"[cyan]Outil : {outil}[/cyan]")
        _console.print(f"[cyan]Args : {args_json}[/cyan]")
    
    confirmation = _console.input("[bold]Confirmer la modification ? (Carl-William uniquement - o/n) >[/bold] ").strip().lower()
    
    if confirmation not in {"o", "oui", "yes", "y"}:
        return "Modification annulée."
    
    # Pour l'instant, cette fonction ne modifie pas réellement le fichier core/translator.py
    # car cela nécessiterait une réécriture du fichier source, ce qui est risqué.
    # À l'avenir, cela pourrait être implémenté via un système de persistance séparé.
    
    return "Modification du traducteur en attente d'implémentation de persistance sécurisée."


OUTILS = {
    "creer_dossier": creer_dossier,
    "creer_fichier": creer_fichier,
    "lire_fichier": lire_fichier,
    "lister_dossier": lister_dossier,
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
    "notifier_utilisateur": notifier_utilisateur,
    "executer_commande": executer_commande,
    "executer_powershell": executer_powershell,
    "terminer_tache": terminer_tache,
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
    "ajouter_automatisation": ajouter_automatisation_tool,
    "lister_automatisations": lister_automatisations,
    "executer_automatisation": executer_automatisation,
    "executer_automatisations_dues": executer_automatisations_dues,
    "proposer_surveillance_dossiers": proposer_surveillance_dossiers,
    "ajouter_surveillance_dossier": ajouter_surveillance_dossier_tool,
    "lister_surveillance_dossiers": lister_surveillance_dossiers,
    "executer_surveillance_dossiers": executer_surveillance_dossiers,
    "supprimer_surveillance_dossier": supprimer_surveillance_dossier,
    "bilan_proactif": bilan_proactif,
    "lire_traducteur": lire_traducteur_tool,
    "modifier_traducteur": modifier_traducteur,
}
