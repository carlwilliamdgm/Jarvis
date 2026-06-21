"""Single source of truth for tool signatures exposed to LLM prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureOutil:
    nom: str
    signature: str


SIGNATURES_OUTILS = [
    SignatureOutil("creer_dossier", "creer_dossier(chemin: str)"),
    SignatureOutil("creer_fichier", 'creer_fichier(chemin: str, contenu: str = "")'),
    SignatureOutil("lire_fichier", "lire_fichier(chemin: str, max_caracteres: int = 200000)"),
    SignatureOutil("lister_dossier", "lister_dossier(chemin: str, limite: int = 200)"),
    SignatureOutil("supprimer", "supprimer(chemin: str)"),
    SignatureOutil("noter", "noter(note: str)"),
    SignatureOutil("lire_notes", "lire_notes()"),
    SignatureOutil("memoriser_contexte", "memoriser_contexte(categorie: str, cle: str, valeur: str)"),
    SignatureOutil("lire_contexte", "lire_contexte(categorie: str | None = None)"),
    SignatureOutil("oublier_contexte", "oublier_contexte(categorie: str, cle: str)"),
    SignatureOutil("enregistrer_echange", "enregistrer_echange(utilisateur: str, jarvis: str)"),
    SignatureOutil("audit_stockage", "audit_stockage()"),
    SignatureOutil("top_fichiers_lourds", "top_fichiers_lourds(n: int = 10, complet: bool = False, max_secondes: int = 15)"),
    SignatureOutil("vider_temp", "vider_temp()"),
    SignatureOutil("vider_corbeille", "vider_corbeille()"),
    SignatureOutil("notifier_utilisateur", "notifier_utilisateur(titre: str, message: str, urgence: bool = False)"),
    SignatureOutil("executer_commande", "executer_commande(commande: str)"),
    SignatureOutil("executer_powershell", "executer_powershell(commande: str)"),
    SignatureOutil("terminer_tache", 'terminer_tache(resume: str = "Tache terminee.")'),
    SignatureOutil("analyser_organisation", "analyser_organisation(chemin: str)"),
    SignatureOutil("organiser_dossier", "organiser_dossier(chemin: str)"),
    SignatureOutil("ajouter_rappel", "ajouter_rappel(message: str, heure: str)"),
    SignatureOutil("lire_rappels", "lire_rappels()"),
    SignatureOutil("supprimer_rappel", "supprimer_rappel(rappel_id: int)"),
    SignatureOutil("verifier_rappels", "verifier_rappels()"),
    SignatureOutil("memoriser_preference", "memoriser_preference(cle: str, valeur: str)"),
    SignatureOutil("lire_preferences", "lire_preferences()"),
    SignatureOutil("oublier_preference", "oublier_preference(cle: str)"),
    SignatureOutil("ajouter_commande_personnalisee", 'ajouter_commande_personnalisee(nom: str, commande: str, description: str = "")'),
    SignatureOutil("lister_commandes_personnalisees", "lister_commandes_personnalisees()"),
    SignatureOutil("executer_commande_personnalisee", "executer_commande_personnalisee(nom: str)"),
    SignatureOutil("ajouter_automatisation", 'ajouter_automatisation(nom: str, outil: str, args: dict | None = None, recurrence: str = "quotidien", heure: str = "09:00")'),
    SignatureOutil("lister_automatisations", "lister_automatisations()"),
    SignatureOutil("executer_automatisation", "executer_automatisation(automation_id: int | None = None, nom: str | None = None)"),
    SignatureOutil("executer_automatisations_dues", "executer_automatisations_dues()"),
    SignatureOutil("proposer_surveillance_dossiers", "proposer_surveillance_dossiers()"),
    SignatureOutil("ajouter_surveillance_dossier", 'ajouter_surveillance_dossier(chemin: str, recurrence: str = "quotidien", heure: str = "09:00")'),
    SignatureOutil("lister_surveillance_dossiers", "lister_surveillance_dossiers()"),
    SignatureOutil("executer_surveillance_dossiers", "executer_surveillance_dossiers(force: bool = False)"),
    SignatureOutil("supprimer_surveillance_dossier", "supprimer_surveillance_dossier(watcher_id: int)"),
    SignatureOutil("bilan_proactif", 'bilan_proactif(force: bool = False, niveau: str = "normal")'),
    SignatureOutil("lire_traducteur", "lire_traducteur()"),
    SignatureOutil("modifier_traducteur", 'modifier_traducteur(cle: str, patterns_fr: str, patterns_en: str, outil: str = "", args_json: str = "{}")'),
]


def documenter_signatures_outils() -> str:
    """Return a prompt-ready list of exact public tool signatures."""
    lignes = ["Outils disponibles avec leurs signatures exactes :", ""]
    lignes.extend(signature.signature for signature in SIGNATURES_OUTILS)
    lignes.extend([
        "",
        "RÈGLE ABSOLUE : utilise EXACTEMENT les noms de paramètres ci-dessus.",
        "executer_commande → paramètre : commande (pas cmd, pas command)",
        "executer_powershell → paramètre : commande (pas cmd, pas command)",
        "noter → paramètre : note (pas contenu)",
        "memoriser_contexte / lire_contexte / oublier_contexte → paramètre categorie pour les catégories valides : profil, style, habitudes, objectifs, projets, contraintes, faits",
        "supprimer_surveillance_dossier → paramètre : watcher_id (l'identifiant numérique, pas le chemin)",
    ])
    return "\n".join(lignes)
