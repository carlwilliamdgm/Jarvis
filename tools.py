#tools.py

import getpass
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
from core.pattern_analyzer import obtenir_patterns_actuels, detecter_automatisations_potentielles
from core.contextual_suggestions import generer_suggestions_contextuelles, formater_suggestions
from core.system_monitor import generer_rapport_systeme, obtenir_tendances_systeme
from core.decision_analyzer import generer_rapport_performance, obtenir_insights_apprentissage
from core.semantic_search import analyser_insights, enrichir_memoire_avec_metadonnees, rechercher_semantique, formater_resultats_recherche
from capabilities.calendar_integration import obtenir_evenements_aujourdhui, verifier_rappels_calendrier, formater_evenements
from capabilities.email_integration import obtenir_resume_emails, detecter_emails_urgents
from capabilities.web_search import (
    rechercher_web,
    analyser_page_web,
    rechercher_et_analyser,
    extraire_informations_cles,
    synthetiser_resultats
)
from capabilities.browser_automation import (
    naviguer_vers,
    cliquer_element,
    remplir_formulaire,
    extraire_texte,
    prendre_capture,
    executer_sequence,
    obtenir_infos_page
)
from core.browser_session import get_session_manager
from core.browser_overlay import start_browser_overlay, stop_browser_overlay, get_browser_overlay
from core.error_classification import resultat_erreur
from core.confirmations import request_streaming_confirmation
from core.safety import action_requiert_confirmation, chemin_autorise, est_mode_stark_actif
from core.translator import lire_traducteur, obtenir_stats_traducteur
from rich.console import Console

_console = Console()


def demander_confirmation(description: str) -> bool:
    if est_mode_stark_actif():
        return True

    decision = request_streaming_confirmation(description)
    if decision is not None:
        return decision

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
            return resultat_erreur("Creation de dossier annulee.", categorie="action_refusee_par_confirmation")
        return creer_dossier_direct(chemin=str(path))
    except OSError as e:
        return resultat_erreur(f"Erreur : {e}", e)
    except Exception as e:
        return resultat_erreur(f"Erreur : {e}")


def creer_fichier(chemin: str, contenu: str = "") -> str:
    try:
        path = chemin_autorise(chemin)
        if not confirmer_ecriture_si_requise(path, f"creer le fichier {path}"):
            return resultat_erreur("Creation de fichier annulee.", categorie="action_refusee_par_confirmation")
        return creer_fichier_direct(chemin=str(path), contenu=contenu)
    except OSError as e:
        return resultat_erreur(f"Erreur : {e}", e)
    except Exception as e:
        return resultat_erreur(f"Erreur : {e}")


def supprimer(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        if not confirmer_ecriture_si_requise(path, f"supprimer {path}"):
            return resultat_erreur("Suppression annulee.", categorie="action_refusee_par_confirmation")
        return supprimer_direct(chemin=str(path))
    except OSError as e:
        return resultat_erreur(f"Erreur : {e}", e)
    except Exception as e:
        return resultat_erreur(f"Erreur : {e}")


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
            return resultat_erreur("Organisation annulee.", categorie="action_refusee_par_confirmation")
        resultat = organiser_dossier_direct(chemin=str(dossier))
        journaliser_action("organiser_dossier", {"chemin": str(dossier)}, f"{plan}\n{resultat}")
        return resultat
    except OSError as e:
        return resultat_erreur(f"Erreur : {e}", e)
    except Exception as e:
        return resultat_erreur(f"Erreur : {e}")


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


def lire_capacites() -> str:
    """Retourne l'inventaire actuel des outils publics de Jarvis."""
    from core.tool_signatures import documenter_signatures_outils

    return documenter_signatures_outils()


def modifier_traducteur(cle: str, patterns_fr: str, patterns_en: str, outil: str = "", args_json: str = "{}") -> str:
    """
    Modifie ou ajoute une entrée au traducteur.
    
    Confirmation utilisateur OBLIGATOIRE avant écriture.
    """
    # Demander confirmation
    _console.print(f"\n[yellow]⚠️  Modification du traducteur demandée[/yellow]")
    _console.print(f"[cyan]Clé : {cle}[/cyan]")
    _console.print(f"[cyan]Patterns FR : {patterns_fr}[/cyan]")
    _console.print(f"[cyan]Patterns EN : {patterns_en}[/cyan]")
    if outil:
        _console.print(f"[cyan]Outil : {outil}[/cyan]")
        _console.print(f"[cyan]Args : {args_json}[/cyan]")
    
    utilisateur = getpass.getuser() or "utilisateur courant"
    confirmation = _console.input(f"[bold]Confirmer la modification ? ({utilisateur} uniquement - o/n) >[/bold] ").strip().lower()
    
    if confirmation not in {"o", "oui", "yes", "y"}:
        return "Modification annulée."
    
    # Pour l'instant, cette fonction ne modifie pas réellement le fichier core/translator.py
    # car cela nécessiterait une réécriture du fichier source, ce qui est risqué.
    # À l'avenir, cela pourrait être implémenté via un système de persistance séparé.
    
    return "Modification du traducteur en attente d'implémentation de persistance sécurisée."


def suggerer_actions() -> str:
    """
    Génère et affiche des suggestions contextuelles intelligentes.
    
    Cette fonction analyse le contexte actuel, les patterns comportementaux
    et l'état système pour proposer des actions pertinentes à l'utilisateur.
    """
    suggestions = generer_suggestions_contextuelles()
    return formater_suggestions(suggestions)


def analyser_patterns() -> str:
    """
    Analyse et affiche les patterns comportementaux détectés.
    
    Cette fonction examine l'historique d'actions et de conversations
    pour identifier les habitudes et patterns d'utilisation.
    """
    return obtenir_patterns_actuels()


def detecter_automatisations() -> str:
    """
    Détecte et suggère des automatisations potentielles.
    
    Cette fonction analyse les patterns comportementaux pour identifier
    des actions répétitives qui pourraient être automatisées.
    """
    automatisations = detecter_automatisations_potentielles()
    
    if not automatisations:
        return "Aucune automatisation potentielle détectée pour le moment."
    
    lignes = ["=== AUTOMATISATIONS POTENTIELLES ==="]
    for i, auto in enumerate(automatisations, 1):
        pertinence_emoji = {
            "haute": "🔴",
            "moyenne": "🟡",
            "basse": "🟢"
        }.get(auto.get("pertinence", "moyenne"), "🟡")
        
        lignes.append(f"\n{i}. {pertinence_emoji} {auto.get('suggestion', 'Automatisation')}")
        lignes.append(f"   Fréquence : {auto.get('frequence', 'inconnue')}")
        lignes.append(f"   Pertinence : {auto.get('pertinence', 'moyenne')}")
    
    lignes.append("\nPour créer une automatisation, utilisez l'outil 'ajouter_automatisation'.")
    return "\n".join(lignes)


def rapport_systeme() -> str:
    """
    Génère un rapport complet de l'état système.
    
    Cette fonction surveille CPU, mémoire, disque, réseau et détecte les anomalies.
    """
    return generer_rapport_systeme()


def tendances_systeme(heures: int = 24) -> str:
    """
    Analyse les tendances système sur une période donnée.
    
    Args:
        heures: Nombre d'heures à analyser
        
    Returns:
        Tendances détectées (CPU, mémoire, disque)
    """
    tendances = obtenir_tendances_systeme(heures)
    
    if "message" in tendances:
        return tendances["message"]
    
    lignes = ["=== TENDANCES SYSTÈME ==="]
    lignes.append(f"Période analysée : {tendances['periode_analysee']}")
    lignes.append(f"Données analysées : {tendances['nombre_donnees']} points")
    lignes.append(f"\nCPU moyen : {tendances['cpu_moyen']}%")
    lignes.append(f"Tendance CPU : {tendances['cpu_tendance']}")
    lignes.append(f"\nMémoire moyenne : {tendances['memoire_moyenne']}%")
    lignes.append(f"\nDisque moyen : {tendances['disque_moyen']}%")
    lignes.append(f"\nAnalyse effectuée : {tendances['timestamp_analyse']}")
    
    return "\n".join(lignes)


def evenements_aujourdhui() -> str:
    """
    Obtient les événements calendrier pour aujourd'hui.
    
    Returns:
        Liste des événements du jour
    """
    evenements = obtenir_evenements_aujourdhui()
    return formater_evenements(evenements)


def rappels_calendrier() -> str:
    """
    Vérifie les rappels de calendrier imminents.
    
    Returns:
        Liste des événements avec rappels dans l'heure suivante
    """
    rappels = verifier_rappels_calendrier()
    
    if not rappels:
        return "Aucun rappel calendrier dans l'heure suivante."
    
    lignes = ["=== RAPPELS CALENDRIER ==="]
    for rappel in rappels:
        lignes.append(f"\n📅 {rappel.get('titre', 'Sans titre')}")
        lignes.append(f"   Dans {rappel.get('minutes_restant', 0)} minutes")
        if rappel.get("lieu"):
            lignes.append(f"   📍 {rappel['lieu']}")
    
    return "\n".join(lignes)


def resume_emails() -> str:
    """
    Obtient un résumé de la situation email.
    
    Returns:
        Résumé des emails non lus, urgents et patterns
    """
    return obtenir_resume_emails()


def emails_urgents() -> str:
    """
    Détecte et affiche les emails urgents.
    
    Returns:
        Liste des emails marqués comme urgents
    """
    urgents = detecter_emails_urgents()
    
    if not urgents or ("erreur" in urgents[0]):
        return "Aucun email urgent détecté ou erreur d'accès."
    
    lignes = [f"=== EMAILS URGENTS ({len(urgents)}) ==="]
    for email in urgents:
        lignes.append(f"\n🔴 {email.get('sujet', 'Sans sujet')}")
        lignes.append(f"   De : {email.get('nom_expediteur', 'Inconnu')}")
        lignes.append(f"   Raison : {email.get('raison', 'importance')}")
    
    return "\n".join(lignes)


def rapport_performance() -> str:
    """
    Génère un rapport de performance de Jarvis.
    
    Returns:
        Rapport détaillé des décisions, succès et patterns d'erreur
    """
    return generer_rapport_performance()


def insights_apprentissage() -> str:
    """
    Obtient des insights basés sur les apprentissages enregistrés.
    
    Returns:
        Insights sur l'évolution et l'apprentissage de Jarvis
    """
    return obtenir_insights_apprentissage()


def generer_rapport_conscience() -> str:
    """
    Génère un rapport complet de conscience Jarvis.
    
    Returns:
        Rapport synthétique incluant patterns, système, performance et apprentissage
    """
    lignes = ["=== RAPPORT CONSCIENCE JARVIS ==="]
    lignes.append(f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Patterns comportementaux
    lignes.append("\n--- PATTERNS COMPORTEMENTAUX ---")
    patterns = obtenir_patterns_actuels()
    lignes.append(patterns)
    
    # État système
    lignes.append("\n--- ÉTAT SYSTÈME ---")
    systeme = generer_rapport_systeme()
    lignes.append(systeme)
    
    # Performance
    lignes.append("\n--- PERFORMANCE ---")
    performance = generer_rapport_performance()
    lignes.append(performance)
    
    # Apprentissage
    lignes.append("\n--- APPRENTISSAGE ---")
    apprentissage = obtenir_insights_apprentissage()
    lignes.append(apprentissage)
    
    # Suggestions proactives
    lignes.append("\n--- SUGGESTIONS PROACTIVES ---")
    suggestions = suggerer_actions()
    lignes.append(suggestions)
    
    lignes.append("\n=== FIN DU RAPPORT ===")
    
    return "\n".join(lignes)


def analyser_insights() -> str:
    """
    Analyse et affiche les insights profonds basés sur la recherche sémantique.
    
    Returns:
        Insights sur les connexions contextuelles et patterns profonds
    """
    return analyser_insights()


def enrichir_memoire() -> str:
    """
    Enrichit la mémoire avec des métadonnées temporelles et contextuelles.
    
    Returns:
        Résultat de l'enrichissement de la mémoire
    """
    return enrichir_memoire_avec_metadonnees()


def rechercher(requete: str) -> str:
    """
    Effectue une recherche sémantique dans les interactions passées.
    
    Args:
        requete: La requête de recherche
        
    Returns:
        Résultats de la recherche triés par pertinence
    """
    resultats = rechercher_semantique(requete)
    return formater_resultats_recherche(resultats)


def rechercher_web_tool(requete: str, nombre_resultats: int = 5) -> str:
    """
    Effectue une recherche web et retourne les résultats.
    
    Args:
        requete: La requête de recherche
        nombre_resultats: Nombre de résultats à retourner (max 10)
        
    Returns:
        Résultats de recherche formatés
    """
    try:
        return rechercher_web(requete, nombre_resultats)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la recherche web: {str(e)}", e)


def analyser_page_web_tool(url: str) -> str:
    """
    Analyse et extrait le contenu d'une page web.
    
    Args:
        url: URL de la page à analyser
        
    Returns:
        Contenu extrait et analysé de la page
    """
    try:
        return analyser_page_web(url)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'analyse de la page: {str(e)}", e)


def rechercher_et_analyser_tool(requete: str, nombre_pages: int = 3) -> str:
    """
    Effectue une recherche web et analyse le contenu des pages les plus pertinentes.
    
    Args:
        requete: La requête de recherche
        nombre_pages: Nombre de pages à analyser en détail
        
    Returns:
        Synthèse de la recherche avec analyse des contenus
    """
    try:
        return rechercher_et_analyser(requete, nombre_pages)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la recherche et analyse: {str(e)}", e)


def extraire_informations_cles_tool(texte: str) -> str:
    """
    Extrait les informations clés d'un texte (nombres, dates, emails, URLs).
    
    Args:
        texte: Le texte à analyser
        
    Returns:
        Informations clés extraites
    """
    try:
        return extraire_informations_cles(texte)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'extraction d'informations: {str(e)}", e)


def synthetiser_resultats_tool(resultats: list) -> str:
    """
    Synthétise plusieurs résultats de recherche en un résumé cohérent.
    
    Args:
        resultats: Liste des résultats à synthétiser
        
    Returns:
        Synthèse des résultats
    """
    try:
        return synthetiser_resultats(resultats)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la synthèse: {str(e)}", e)


def naviguer_vers_tool(url: str, headless: bool = True) -> str:
    """
    Navigue vers une URL spécifique dans un navigateur automatisé.
    
    Args:
        url: URL vers laquelle naviguer
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat de la navigation
    """
    try:
        return naviguer_vers(url, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la navigation: {str(e)}", e)


def cliquer_element_tool(selector: str, url: str = None, headless: bool = True) -> str:
    """
    Clique sur un élément de la page web.
    
    Args:
        selector: Sélecteur CSS ou XPath de l'élément
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat du clic
    """
    try:
        return cliquer_element(selector, url, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors du clic: {str(e)}", e)


def remplir_formulaire_tool(selector: str, valeur: str, url: str = None, headless: bool = True) -> str:
    """
    Remplit un champ de formulaire avec une valeur.
    
    Args:
        selector: Sélecteur CSS ou XPath du champ
        valeur: Valeur à insérer
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat du remplissage
    """
    try:
        return remplir_formulaire(selector, valeur, url, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors du remplissage: {str(e)}", e)


def extraire_texte_page_tool(selector: str = "body", url: str = None, headless: bool = True) -> str:
    """
    Extrait le texte d'un élément ou de la page entière.
    
    Args:
        selector: Sélecteur CSS ou XPath (défaut: body)
        url: URL optionnelle où naviguer d'abord
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Texte extrait
    """
    try:
        return extraire_texte(selector, url, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'extraction: {str(e)}", e)


def prendre_capture_tool(path: str = None, url: str = None, full_page: bool = False, headless: bool = True) -> str:
    """
    Prend une capture d'écran de la page web.
    
    Args:
        path: Chemin où sauvegarder (optionnel)
        url: URL optionnelle où naviguer d'abord
        full_page: Si True, capture toute la page
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultat de la capture
    """
    try:
        return prendre_capture(path, url, full_page, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la capture: {str(e)}", e)


def executer_sequence_tool(actions: list, headless: bool = True) -> str:
    """
    Exécute une séquence d'actions de navigation.
    
    Args:
        actions: Liste d'actions à exécuter (dictionnaires avec 'type' et paramètres)
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Résultats de toutes les actions
    """
    try:
        return executer_sequence(actions, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'exécution: {str(e)}", e)


def obtenir_infos_page_tool(url: str = None, headless: bool = True) -> str:
    """
    Obtient des informations détaillées sur la page web.
    
    Args:
        url: URL optionnelle où naviguer
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Informations sur la page
    """
    try:
        return obtenir_infos_page(url, headless)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'obtention des infos: {str(e)}", e)


def demarrer_overlay_navigation() -> str:
    """
    Démarre l'overlay visuel de navigation en temps réel.
    
    Returns:
        Message de confirmation
    """
    try:
        result = start_browser_overlay()
        if result:
            return "Overlay de navigation démarré avec succès"
        else:
            return "L'overlay de navigation est déjà en cours d'exécution"
    except Exception as e:
        return resultat_erreur(f"Erreur lors du démarrage de l'overlay: {str(e)}", e)


def arreter_overlay_navigation() -> str:
    """
    Arrête l'overlay visuel de navigation.
    
    Returns:
        Message de confirmation
    """
    try:
        stop_browser_overlay()
        return "Overlay de navigation arrêté"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'arrêt de l'overlay: {str(e)}", e)


def creer_session_navigation(session_id: str, headless: bool = True) -> str:
    """
    Crée une nouvelle session de navigation parallèle.
    
    Args:
        session_id: Identifiant unique de la session
        headless: Si True, exécute sans interface graphique
        
    Returns:
        Message de confirmation
    """
    try:
        import time
        manager = get_session_manager()
        session = manager.create_session(session_id, headless)
        
        # Attendre que la session soit prête
        time.sleep(3)
        
        if session.state.value == "idle":
            return f"Session de navigation '{session_id}' créée avec succès et prête"
        elif session.state.value == "error":
            return f"Session créée mais erreur: {session.error_message}"
        else:
            return f"Session créée, état actuel: {session.state.value}"
            
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la création de session: {str(e)}", e)


def naviguer_session(session_id: str, url: str) -> str:
    """
    Navigue vers une URL dans une session spécifique (non-bloquant).
    
    Args:
        session_id: Identifiant de la session
        url: URL vers laquelle naviguer
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        result = session.navigate(url)
        if result:
            return f"Navigation vers {url} lancée dans la session '{session_id}'"
        else:
            return f"Impossible de lancer la navigation dans la session '{session_id}'"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la navigation: {str(e)}", e)


def cliquer_session(session_id: str, selector: str) -> str:
    """
    Clique sur un élément dans une session spécifique (non-bloquant).
    
    Args:
        session_id: Identifiant de la session
        selector: Sélecteur CSS ou XPath de l'élément
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        result = session.click(selector)
        if result:
            return f"Clic sur {selector} lancé dans la session '{session_id}'"
        else:
            return f"Impossible de cliquer dans la session '{session_id}'"
    except Exception as e:
        return resultat_erreur(f"Erreur lors du clic: {str(e)}", e)


def remplir_session(session_id: str, selector: str, valeur: str) -> str:
    """
    Remplit un champ dans une session spécifique (non-bloquant).
    
    Args:
        session_id: Identifiant de la session
        selector: Sélecteur CSS ou XPath du champ
        valeur: Valeur à insérer
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        result = session.fill(selector, valeur)
        if result:
            return f"Remplissage de {selector} lancé dans la session '{session_id}'"
        else:
            return f"Impossible de remplir dans la session '{session_id}'"
    except Exception as e:
        return resultat_erreur(f"Erreur lors du remplissage: {str(e)}", e)


def capture_session(session_id: str) -> str:
    """
    Prend une capture d'écran dans une session spécifique (non-bloquant).
    
    Args:
        session_id: Identifiant de la session
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        result = session.screenshot()
        if result:
            return f"Capture d'écran lancée dans la session '{session_id}'"
        else:
            return f"Impossible de prendre une capture dans la session '{session_id}'"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la capture: {str(e)}", e)


def executer_js_session(session_id: str, script: str) -> str:
    """
    Exécute du JavaScript dans une session spécifique (non-bloquant).
    
    Args:
        session_id: Identifiant de la session
        script: Code JavaScript à exécuter
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        result = session.execute_javascript(script)
        if result:
            return f"Exécution JavaScript lancée dans la session '{session_id}'"
        else:
            return f"Impossible d'exécuter JavaScript dans la session '{session_id}'"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'exécution JavaScript: {str(e)}", e)


def fermer_session(session_id: str) -> str:
    """
    Ferme une session de navigation.
    
    Args:
        session_id: Identifiant de la session
        
    Returns:
        Message de confirmation
    """
    try:
        manager = get_session_manager()
        manager.close_session(session_id)
        return f"Session '{session_id}' fermée"
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la fermeture: {str(e)}", e)


def lister_sessions() -> str:
    """
    Liste toutes les sessions de navigation actives.
    
    Returns:
        Liste des sessions avec leur état
    """
    try:
        manager = get_session_manager()
        sessions = manager.get_all_sessions()
        
        if not sessions:
            return "Aucune session de navigation active"
        
        lignes = ["=== SESSIONS DE NAVIGATION ACTIVES ==="]
        for session in sessions:
            lignes.append(f"\nSession: {session.get('session_id', 'Unknown')}")
            lignes.append(f"  État: {session.get('state', 'unknown')}")
            lignes.append(f"  URL: {session.get('current_url', 'N/A')}")
            lignes.append(f"  Titre: {session.get('current_title', 'N/A')}")
            lignes.append(f"  Actions: {session.get('actions_count', 0)}")
            lignes.append(f"  Screenshot: {'Oui' if session.get('has_screenshot') else 'Non'}")
        
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la liste: {str(e)}", e)


def obtenir_etat_session(session_id: str) -> str:
    """
    Obtient l'état détaillé d'une session spécifique.
    
    Args:
        session_id: Identifiant de la session
        
    Returns:
        État détaillé de la session
    """
    try:
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return f"Session '{session_id}' non trouvée"
        
        state = session.get_state()
        lignes = [f"=== ÉTAT SESSION '{session_id}' ==="]
        lignes.append(f"État: {state.get('state', 'unknown')}")
        lignes.append(f"URL: {state.get('current_url', 'N/A')}")
        lignes.append(f"Titre: {state.get('current_title', 'N/A')}")
        lignes.append(f"Dernière activité: {state.get('last_activity', 'N/A')}")
        lignes.append(f"Actions effectuées: {state.get('actions_count', 0)}")
        lignes.append(f"Screenshot disponible: {'Oui' if state.get('has_screenshot') else 'Non'}")
        lignes.append(f"Longueur contenu: {state.get('content_length', 0)} caractères")
        
        if state.get('error_message'):
            lignes.append(f"Erreur: {state.get('error_message')}")
        
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de l'obtention de l'état: {str(e)}", e)


def decouvrir_appareils_tailscale() -> str:
    """Détecte et liste les appareils connectés sur le réseau privé Tailscale."""
    try:
        from api.server import obtenir_infos_tailscale
        info = obtenir_infos_tailscale()
        if not info.get("disponible"):
            return "Tailscale n'est pas disponible ou actif sur cette machine."
        self_info = info.get("self", {})
        devices = info.get("devices", [])
        lignes = [f"Machine locale : {self_info.get('nom', 'Inconnue')} ({self_info.get('ip', 'Pas d\'IP')})"]
        if not devices:
            lignes.append("Aucun appareil distant détecté sur le Tailnet.")
        else:
            lignes.append("Appareils sur le Tailnet :")
            for d in devices:
                statut = "🟢 en ligne" if d.get("online") else "⚪ hors ligne"
                lignes.append(f"- {d.get('nom')} ({d.get('ip')}) [{d.get('os')}] : {statut}")
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur lors de la détection Tailscale: {str(e)}", e)


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
    "lire_capacites": lire_capacites,
    "lire_traducteur": lire_traducteur_tool,
    "modifier_traducteur": modifier_traducteur,
    "suggerer_actions": suggerer_actions,
    "analyser_patterns": analyser_patterns,
    "detecter_automatisations": detecter_automatisations,
    "rapport_systeme": rapport_systeme,
    "tendances_systeme": tendances_systeme,
    "evenements_aujourdhui": evenements_aujourdhui,
    "rappels_calendrier": rappels_calendrier,
    "resume_emails": resume_emails,
    "emails_urgents": emails_urgents,
    "rapport_performance": rapport_performance,
    "insights_apprentissage": insights_apprentissage,
    "generer_rapport_conscience": generer_rapport_conscience,
    "analyser_insights": analyser_insights,
    "enrichir_memoire": enrichir_memoire,
    "rechercher": rechercher,
    "rechercher_web": rechercher_web_tool,
    "analyser_page_web": analyser_page_web_tool,
    "rechercher_et_analyser": rechercher_et_analyser_tool,
    "extraire_informations_cles": extraire_informations_cles_tool,
    "synthetiser_resultats": synthetiser_resultats_tool,
    "naviguer_vers": naviguer_vers_tool,
    "cliquer_element": cliquer_element_tool,
    "remplir_formulaire": remplir_formulaire_tool,
    "extraire_texte_page": extraire_texte_page_tool,
    "prendre_capture": prendre_capture_tool,
    "executer_sequence": executer_sequence_tool,
    "obtenir_infos_page": obtenir_infos_page_tool,
    "demarrer_overlay_navigation": demarrer_overlay_navigation,
    "arreter_overlay_navigation": arreter_overlay_navigation,
    "creer_session_navigation": creer_session_navigation,
    "naviguer_session": naviguer_session,
    "cliquer_session": cliquer_session,
    "remplir_session": remplir_session,
    "capture_session": capture_session,
    "executer_js_session": executer_js_session,
    "fermer_session": fermer_session,
    "lister_sessions": lister_sessions,
    "obtenir_etat_session": obtenir_etat_session,
    "decouvrir_appareils_tailscale": decouvrir_appareils_tailscale,
}
