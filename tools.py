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
from core.safety import DANGEROUS_ACTIONS, chemin_autorise, racine_trop_large


def demander_confirmation(outil: str, args: dict, description: str) -> str:
    if outil not in DANGEROUS_ACTIONS:
        raise ValueError(f"Action non dangereuse inattendue : {outil}")

    data = normaliser_memoire(charger_memoire())
    actions = data.get("actions_en_attente", [])
    action_id = max([a.get("id", 0) for a in actions], default=0) + 1
    actions.append({
        "id": action_id,
        "outil": outil,
        "args": args,
        "description": description,
        "statut": "en attente",
        "cree_le": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["actions_en_attente"] = actions[-20:]
    sauvegarder_memoire(data)
    return (
        f"Confirmation requise pour l'action #{action_id} : {description}\n"
        f"Pour l'executer, appelez confirmer_action(action_id={action_id})."
    )


def confirmer_action(action_id: int) -> str:
    data = normaliser_memoire(charger_memoire())
    actions = data.get("actions_en_attente", [])
    action = next((a for a in actions if a.get("id") == int(action_id) and a.get("statut") == "en attente"), None)
    if not action:
        return f"Action #{action_id} introuvable ou deja traitee."

    outil = action["outil"]
    args = action.get("args", {})
    try:
        if outil == "supprimer":
            resultat = supprimer_direct(**args)
        elif outil == "vider_temp":
            resultat = storage.vider_temp()
        elif outil == "vider_corbeille":
            resultat = storage.vider_corbeille()
        elif outil == "executer_commande":
            resultat = executer_commande_direct(**args)
        elif outil == "organiser_dossier":
            resultat = organiser_dossier_direct(**args)
        else:
            resultat = f"Outil non confirmable : {outil}"
    except Exception as e:
        resultat = f"Erreur : {e}"

    action["statut"] = "execute"
    action["execute_le"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["actions_en_attente"] = actions
    sauvegarder_memoire(data)
    journaliser_action(outil, args, resultat)
    return resultat


def annuler_action(action_id: int) -> str:
    data = normaliser_memoire(charger_memoire())
    actions = data.get("actions_en_attente", [])
    action = next((a for a in actions if a.get("id") == int(action_id) and a.get("statut") == "en attente"), None)
    if not action:
        return f"Action #{action_id} introuvable ou deja traitee."
    action["statut"] = "annulee"
    action["annulee_le"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["actions_en_attente"] = actions
    sauvegarder_memoire(data)
    return f"Action #{action_id} annulee."


def supprimer(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        return demander_confirmation("supprimer", {"chemin": str(path)}, f"supprimer {path}")
    except Exception as e:
        return f"Erreur : {e}"


def executer_commande(commande: str) -> str:
    try:
        return demander_confirmation("executer_commande", {"commande": commande}, f"executer la commande : {commande}")
    except Exception as e:
        return f"Erreur : {e}"


def vider_temp() -> str:
    return demander_confirmation("vider_temp", {}, "vider les fichiers temporaires")


def vider_corbeille() -> str:
    return demander_confirmation("vider_corbeille", {}, "vider la corbeille")


def organiser_dossier(chemin: str) -> str:
    try:
        dossier = chemin_autorise(chemin, doit_exister=True)
        if racine_trop_large(dossier):
            return f"Organisation refusee pour une racine trop large : {dossier}. Ciblez un sous-dossier precis."
        plan = analyser_organisation(str(dossier))
        return demander_confirmation("organiser_dossier", {"chemin": str(dossier)}, f"organiser {dossier}\n{plan}")
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


def action_refusee(action: dict) -> str | None:
    if action.get("outil") == "organiser_dossier":
        chemin = action.get("args", {}).get("chemin")
        if chemin:
            try:
                dossier = chemin_autorise(chemin, doit_exister=True)
            except Exception:
                return "chemin inaccessible"
            if racine_trop_large(dossier):
                return "cible trop large"
    return None


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
    actions = []
    refusees = []
    for action in data.get("actions_en_attente", []):
        if action.get("statut") != "en attente":
            continue
        raison_refus = action_refusee(action)
        if raison_refus:
            action["statut"] = "refusee"
            action["refusee_le"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            action["raison_refus"] = raison_refus
            refusees.append(f"- #{action['id']} : {raison_refus}")
            continue
        actions.append(action)

    if refusees and niveau != "silencieux":
        lignes.append("Actions en attente refusees automatiquement :\n" + "\n".join(refusees))
    if actions and (force or signal_autorise(data, "actions_en_attente", 30)):
        lignes.append(
            "Actions en attente :\n"
            + "\n".join(f"- #{a['id']} : {a.get('description', a.get('outil', 'action'))}" for a in actions[:5])
        )

    try:
        libre = storage.get_stockage()
        if libre <= storage.SEUIL_ROUGE and (force or signal_autorise(data, "stockage_rouge", 30)):
            lignes.append(storage.audit_stockage() + "\nSuggestion : preparer un nettoyage avec vider_temp et audit_stockage.")
        elif niveau != "silencieux" and libre <= storage.SEUIL_ORANGE and (force or signal_autorise(data, "stockage_orange", 120)):
            lignes.append(storage.audit_stockage() + "\nSuggestion : surveiller les gros fichiers avec top_fichiers_lourds.")
    except Exception:
        pass

    contexte = data.get("contexte", {})
    if niveau == "complet" and force and not any(contexte.get(categorie) for categorie in CATEGORIES_CONTEXTE):
        lignes.append("Memoire personnelle peu renseignee : je peux memoriser profil, habitudes, objectifs, projets, contraintes et style.")

    if niveau == "complet" and force and not data.get("automatisations"):
        lignes.append("Aucune automatisation active. Je peux creer des routines locales de verification, rangement ou maintenance.")

    if niveau == "complet" and force and not data.get("surveillances_dossiers"):
        lignes.append("Aucune surveillance de dossier active. Je peux surveiller Downloads, Desktop ou Documents discretement.")

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
    "confirmer_action": confirmer_action,
    "annuler_action": annuler_action,
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
