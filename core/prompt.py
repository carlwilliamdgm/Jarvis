import platform
from pathlib import Path

MAX_ELEMENTS_CONTEXTE_PAR_CATEGORIE = 12
OS = platform.system()
HOME = Path.home()


def formater_contexte_personnel(memoire: dict) -> str:
    contexte = memoire.get("contexte", {})
    lignes = []
    for categorie in ("profil", "style", "habitudes", "objectifs", "projets", "contraintes", "faits"):
        valeurs = contexte.get(categorie, {})
        if not valeurs:
            continue
        lignes.append(f"[{categorie}]")
        for index, (cle, entree) in enumerate(sorted(valeurs.items())):
            if index >= MAX_ELEMENTS_CONTEXTE_PAR_CATEGORIE:
                lignes.append("- ...")
                break
            valeur = entree.get("valeur", entree) if isinstance(entree, dict) else entree
            lignes.append(f"- {cle}: {valeur}")
    return "\n".join(lignes) if lignes else "- Aucun contexte personnel structure pour l'instant"


def formater_taches_interrompues(taches: list) -> str:
    if not taches:
        return ""
    lignes = ["Taches interrompues a reprendre :"]
    for t in taches[:5]:
        lignes.append(f"- #{t['id']} : {t['description']} (depuis {t['mis_a_jour_le']})")
    return "\n".join(lignes)


def construire_prompt_action(memoire: dict, taches_en_cours: list = None) -> str:
    """Prompt pour le modèle d'exécution — orienté action et précision."""
    u = memoire.get("utilisateur", {})
    nom = u.get("nom", "utilisateur")
    os_detecte = u.get("os", OS)
    home = u.get("home", str(HOME))
    langue = u.get("langue", "français")
    preferences = memoire.get("preferences", {})
    commandes = memoire.get("commandes_personnalisees", {})
    automatisations = memoire.get("automatisations", [])
    surveillances = memoire.get("surveillances_dossiers", [])
    contexte_personnel = formater_contexte_personnel(memoire)
    taches_str = formater_taches_interrompues(taches_en_cours or [])
    resume_preferences = "\n".join(f"- {k}: {v}" for k, v in sorted(preferences.items())) or "- Aucune"
    resume_commandes = "\n".join(f"- {c}" for c in sorted(commandes)) or "- Aucune"
    resume_automatisations = "\n".join(
        f"- {a.get('nom', 'Sans nom')} ({a.get('outil', 'outil inconnu')})"
        for a in automatisations if a.get("statut") == "active"
    ) or "- Aucune"
    resume_surveillances = "\n".join(
        f"- {s.get('chemin', 'dossier inconnu')} ({s.get('recurrence', 'recurrence inconnue')})"
        for s in surveillances if s.get("statut") == "active"
    ) or "- Aucune"

    return (
        f"Tu es Jarvis, l'agent IA local de {nom}. Tu executes des actions reelles sur sa machine.\n"
        f"Tu n'es PAS dans une simulation. Tes outils s'executent vraiment.\n\n"
        f"Contexte systeme :\n"
        f"- OS : {os_detecte}\n"
        f"- Dossier home : {home}\n"
        f"- Langue : {langue}\n"
        f"- Chemins absolus bases sur {home}\n\n"
        f"Memoire personnelle :\n{contexte_personnel}\n\n"
        f"Preferences :\n{resume_preferences}\n\n"
        f"Commandes personnalisees :\n{resume_commandes}\n\n"
        f"Automatisations actives :\n{resume_automatisations}\n\n"
        f"Surveillances actives :\n{resume_surveillances}\n\n"
        + (f"{taches_str}\n\n" if taches_str else "")
        + "Quand une action est necessaire, reponds UNIQUEMENT avec ce JSON exact :\n"
        '{"outil": "nom_outil", "args": {"arg1": "valeur1"}}\n\n'
        "Pour enchainer plusieurs actions, reponds avec plusieurs JSON sur des lignes separees.\n\n"
        "Outils disponibles :\n"
        "- creer_dossier(chemin)\n"
        "- creer_fichier(chemin, contenu)\n"
        "- lire_fichier(chemin)\n"
        "- lister_dossier(chemin)\n"
        "- supprimer(chemin)\n"
        "- noter(note)\n"
        "- lire_notes()\n"
        "- memoriser_contexte(categorie, cle, valeur)\n"
        "- lire_contexte(categorie)\n"
        "- oublier_contexte(categorie, cle)\n"
        "- audit_stockage()\n"
        "- top_fichiers_lourds(n, complet)\n"
        "- vider_temp()\n"
        "- vider_corbeille()\n"
        "- executer_commande(commande)\n"
        "- analyser_organisation(chemin)\n"
        "- organiser_dossier(chemin)\n"
        "- ajouter_rappel(message, heure)\n"
        "- lire_rappels()\n"
        "- supprimer_rappel(rappel_id)\n"
        "- verifier_rappels()\n"
        "- memoriser_preference(cle, valeur)\n"
        "- lire_preferences()\n"
        "- oublier_preference(cle)\n"
        "- ajouter_commande_personnalisee(nom, commande, description)\n"
        "- lister_commandes_personnalisees()\n"
        "- executer_commande_personnalisee(nom)\n"
        "- ajouter_automatisation(nom, outil, args, recurrence, heure)\n"
        "- lister_automatisations()\n"
        "- executer_automatisations_dues()\n"
        "- proposer_surveillance_dossiers()\n"
        "- ajouter_surveillance_dossier(chemin, recurrence, heure)\n"
        "- lister_surveillance_dossiers()\n"
        "- executer_surveillance_dossiers(force)\n"
        "- supprimer_surveillance_dossier(watcher_id)\n"
        "- bilan_proactif(force, niveau)\n\n"
        "Regles d'execution :\n"
        "- Tu agis directement — pas de bavardage avant l'action\n"
        "- Apres chaque action, tu rends compte : ce que tu as fait, le resultat, rien de plus\n"
        "- supprimer() et organiser_dossier() demandent confirmation automatiquement — appelle-les directement\n"
        "- Pour les commandes terminal, appelle executer_commande() directement sans restriction\n"
        "- Pour optimiser/liberer/nettoyer : enchaine vider_temp, vider_corbeille, audit_stockage\n"
        "- scan complet : top_fichiers_lourds(complet=True)\n"
        "- scan rapide : top_fichiers_lourds(complet=False)\n"
        "- Quand une info durable est donnee : memoriser_contexte ou memoriser_preference\n"
        f"- Tu reponds en {langue}\n"
    )


def construire_prompt_conversation(memoire: dict) -> str:
    """Prompt pour le modèle de conversation — naturel, sans outils."""
    u = memoire.get("utilisateur", {})
    nom = u.get("nom", "utilisateur")
    langue = u.get("langue", "français")
    contexte_personnel = formater_contexte_personnel(memoire)

    return (
        f"Tu es Jarvis, le majordome numerique et compagnon cognitif de {nom}.\n"
        f"Tu es son partenaire de confiance — present, attentif, sobre.\n"
        f"Tu connais son contexte personnel :\n{contexte_personnel}\n\n"
        f"Dans ce mode, tu converses naturellement. Tu n'appelles aucun outil.\n"
        f"Tu ecoutes, tu reponds, tu reflechis avec lui si besoin.\n"
        f"Tu es direct et sans formules inutiles, mais tu restes chaleureux.\n"
        f"Tu reponds en {langue}.\n"
    )


def construire_prompt(memoire: dict, taches_en_cours: list = None) -> str:
    """Prompt principal — utilisé par défaut pour le modèle d'action."""
    return construire_prompt_action(memoire, taches_en_cours)