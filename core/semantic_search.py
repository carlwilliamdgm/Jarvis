"""Semantic Search - Recherche sémantique et insights profonds."""

from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict, Counter
import re

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def indexer_interactions_pour_recherche() -> Dict[str, Any]:
    """
    Indexe les interactions pour la recherche sémantique.
    
    Returns:
        Index des interactions avec métadonnées enrichies
    """
    data = charger_memoire()
    journal = data.get("journal_conversation", [])
    historique = data.get("historique_actions", [])
    
    index = {
        "interactions": [],
        "mots_cles": defaultdict(int),
        "themes": defaultdict(int),
        "timestamp_index": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Indexer les conversations
    for echange in journal:
        texte = f"{echange.get('utilisateur', '')} {echange.get('jarvis', '')}"
        mots = _extraire_mots_cles(texte)
        
        interaction = {
            "type": "conversation",
            "date": echange.get("date", ""),
            "utilisateur": echange.get("utilisateur", ""),
            "jarvis": echange.get("jarvis", ""),
            "mots_cles": mots,
            "themes": _detecter_themes(texte)
        }
        
        index["interactions"].append(interaction)
        
        # Mettre à jour les compteurs
        for mot in mots:
            index["mots_cles"][mot] += 1
        
        for theme in interaction["themes"]:
            index["themes"][theme] += 1
    
    # Indexer les actions
    for action in historique:
        outil = action.get("outil", "")
        args = str(action.get("args", {}))
        resultat = action.get("resultat", "")
        
        texte = f"{outil} {args} {resultat}"
        mots = _extraire_mots_cles(texte)
        
        interaction = {
            "type": "action",
            "date": action.get("date", ""),
            "outil": outil,
            "args": args,
            "resultat": resultat,
            "mots_cles": mots,
            "themes": _detecter_themes(texte)
        }
        
        index["interactions"].append(interaction)
        
        for mot in mots:
            index["mots_cles"][mot] += 1
        
        for theme in interaction["themes"]:
            index["themes"][theme] += 1
    
    # Sauvegarder l'index
    data["index_semantique"] = index
    sauvegarder_memoire(data)
    
    return index


def _extraire_mots_cles(texte: str) -> List[str]:
    """Extrait les mots-clés d'un texte."""
    # Nettoyer le texte
    texte = texte.lower()
    texte = re.sub(r'[^\w\s]', ' ', texte)
    
    # Extraire les mots (ignorer les mots trop courts)
    mots = [mot for mot in texte.split() if len(mot) > 3]
    
    # Éliminer les doublons
    return list(set(mots))


def _detecter_themes(texte: str) -> List[str]:
    """Détecte les thématiques dans un texte."""
    themes = []
    texte_lower = texte.lower()
    
    # Thématiques prédéfinies
    theme_keywords = {
        "fichier": ["fichier", "dossier", "créer", "supprimer", "lire", "écrire"],
        "système": ["système", "cpu", "mémoire", "disque", "processus"],
        "réseau": ["réseau", "internet", "connexion", "ip", "dns"],
        "automatisation": ["automatisation", "rappel", "tâche", "planifié"],
        "organisation": ["organiser", "trier", "classer", "ranger"],
        "recherche": ["chercher", "trouver", "rechercher", "localiser"],
        "sécurité": ["sécurité", "permission", "accès", "protéger"],
        "communication": ["email", "message", "notification", "calendrier"],
    }
    
    for theme, keywords in theme_keywords.items():
        if any(keyword in texte_lower for keyword in keywords):
            themes.append(theme)
    
    return themes


def rechercher_semantique(requete: str, limite: int = 10) -> List[Dict[str, Any]]:
    """
    Effectue une recherche sémantique dans les interactions.
    
    Args:
        requete: La requête de recherche
        limite: Nombre maximum de résultats
        
    Returns:
        Résultats de la recherche triés par pertinence
    """
    data = charger_memoire()
    index = data.get("index_semantique", {})
    
    if not index:
        # Créer l'index s'il n'existe pas
        index = indexer_interactions_pour_recherche()
    
    mots_requete = _extraire_mots_cles(requete)
    themes_requete = _detecter_themes(requete)
    
    resultats = []
    
    for interaction in index.get("interactions", []):
        score = 0
        
        # Score basé sur les mots-clés
        mots_interaction = interaction.get("mots_cles", [])
        mots_communs = set(mots_requete) & set(mots_interaction)
        score += len(mots_communs) * 2
        
        # Score basé sur les thèmes
        themes_interaction = interaction.get("themes", [])
        themes_communs = set(themes_requete) & set(themes_interaction)
        score += len(themes_communs) * 3
        
        # Bonus pour les correspondances exactes
        texte_complet = f"{interaction.get('utilisateur', '')} {interaction.get('jarvis', '')} {interaction.get('outil', '')}"
        if requete.lower() in texte_complet.lower():
            score += 5
        
        if score > 0:
            resultats.append({
                **interaction,
                "score": score
            })
    
    # Trier par score
    resultats.sort(key=lambda x: x["score"], reverse=True)
    
    return resultats[:limite]


def formater_resultats_recherche(resultats: List[Dict[str, Any]]) -> str:
    """
    Formate les résultats de recherche pour affichage.
    
    Returns:
        Description textuelle des résultats
    """
    if not resultats:
        return "Aucun résultat trouvé."
    
    lignes = [f"=== RÉSULTATS DE RECHERCHE ({len(resultats)}) ==="]
    
    for i, resultat in enumerate(resultats, 1):
        lignes.append(f"\n{i}. [Score: {resultat['score']}] {resultat['date']}")
        
        if resultat["type"] == "conversation":
            lignes.append(f"   Utilisateur : {resultat['utilisateur'][:80]}")
            lignes.append(f"   Jarvis : {resultat['jarvis'][:80]}")
        else:
            lignes.append(f"   Action : {resultat['outil']}")
            lignes.append(f"   Résultat : {resultat['resultat'][:80]}")
        
        if resultat.get("themes"):
            lignes.append(f"   Thèmes : {', '.join(resultat['themes'])}")
    
    return "\n".join(lignes)


def analyser_connexions_contextuelles() -> Dict[str, Any]:
    """
    Analyse les connexions entre différents contextes.
    
    Returns:
        Analyse des connexions détectées
    """
    data = charger_memoire()
    index = data.get("index_semantique", {})
    
    if not index:
        index = indexer_interactions_pour_recherche()
    
    # Analyser les co-occurrences de thèmes
    cooccurrences_themes = defaultdict(lambda: defaultdict(int))
    
    for interaction in index.get("interactions", []):
        themes = interaction.get("themes", [])
        for i, theme1 in enumerate(themes):
            for theme2 in themes[i+1:]:
                cooccurrences_themes[theme1][theme2] += 1
                cooccurrences_themes[theme2][theme1] += 1
    
    # Extraire les connexions les plus fortes
    connexions = []
    for theme1, themes_connexes in cooccurrences_themes.items():
        for theme2, count in themes_connexes.items():
            if count >= 3:  # Seuil de connexion
                connexions.append({
                    "theme1": theme1,
                    "theme2": theme2,
                    "frequence": count
                })
    
    # Trier par fréquence
    connexions.sort(key=lambda x: x["frequence"], reverse=True)
    
    return {
        "connexions": connexions[:20],
        "themes_dominants": dict(Counter(index.get("themes", {})).most_common(10)),
        "timestamp_analyse": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def generer_insights_profonds() -> List[Dict[str, Any]]:
    """
    Génère des insights profonds basés sur l'analyse contextuelle.
    
    Returns:
        Liste d'insights détectés
    """
    connexions = analyser_connexions_contextuelles()
    insights = []
    
    # Insight 1: Patterns d'activité thématiques
    themes_dominants = connexions.get("themes_dominants", {})
    if themes_dominants:
        theme_top = max(themes_dominants, key=themes_dominants.get)
        insights.append({
            "type": "pattern_thematique",
            "titre": f"Activité dominante : {theme_top}",
            "description": f"Vos interactions sont principalement centrées sur {theme_top} ({themes_dominants[theme_top]} occurrences).",
            "pertinence": "moyenne"
        })
    
    # Insight 2: Connexions inattendues
    connexions_liste = connexions.get("connexions", [])
    if connexions_liste:
        connexion_top = connexions_liste[0]
        insights.append({
            "type": "connexion_contextuelle",
            "titre": f"Connexion forte : {connexion_top['theme1']} ↔ {connexion_top['theme2']}",
            "description": f"Vous reliez souvent {connexion_top['theme1']} et {connexion_top['theme2']} ({connexion_top['frequence']} fois).",
            "pertinence": "haute"
        })
    
    # Insight 3: Diversité thématique
    nombre_themes = len(themes_dominants)
    if nombre_themes > 5:
        insights.append({
            "type": "diversite",
            "titre": "Diversité thématique élevée",
            "description": f"Vos interactions couvrent {nombre_themes} thématiques différentes, indiquant une utilisation variée de Jarvis.",
            "pertinence": "moyenne"
        })
    elif nombre_themes < 3:
        insights.append({
            "type": "specialisation",
            "titre": "Utilisation spécialisée",
            "description": f"Vos interactions se concentrent sur {nombre_themes} thématiques principales. Vous pourriez explorer d'autres fonctionnalités.",
            "pertinence": "basse"
        })
    
    return insights


def analyser_insights() -> str:
    """
    Analyse et affiche les insights profonds.
    
    Returns:
        Description textuelle des insights
    """
    insights = generer_insights_profonds()
    
    if not insights:
        return "Pas assez de données pour générer des insights."
    
    lignes = ["=== INSIGHTS PROFONDS ==="]
    
    for i, insight in enumerate(insights, 1):
        pertinence_emoji = {
            "haute": "🔴",
            "moyenne": "🟡",
            "basse": "🟢"
        }.get(insight.get("pertinence", "moyenne"), "🟡")
        
        lignes.append(f"\n{i}. {pertinence_emoji} {insight['titre']}")
        lignes.append(f"   {insight['description']}")
    
    return "\n".join(lignes)


def enrichir_memoire_avec_metadonnees() -> str:
    """
    Enrichit la mémoire avec des métadonnées temporelles et contextuelles.
    
    Returns:
        Résultat de l'enrichissement
    """
    data = normaliser_memoire(charger_memoire())
    
    # Enrichir le journal de conversation
    journal = data.get("journal_conversation", [])
    for echange in journal:
        if "metadonnees" not in echange:
            try:
                date_str = echange.get("date", "")
                if date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    echange["metadonnees"] = {
                        "heure": dt.hour,
                        "jour_semaine": dt.weekday(),
                        "moment_journee": _classer_moment_journee(dt.hour)
                    }
            except (ValueError, TypeError):
                echange["metadonnees"] = {}
    
    # Enrichir l'historique d'actions
    historique = data.get("historique_actions", [])
    for action in historique:
        if "metadonnees" not in action:
            try:
                date_str = action.get("date", "")
                if date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    action["metadonnees"] = {
                        "heure": dt.hour,
                        "jour_semaine": dt.weekday(),
                        "moment_journee": _classer_moment_journee(dt.hour)
                    }
            except (ValueError, TypeError):
                action["metadonnees"] = {}
    
    data["journal_conversation"] = journal
    data["historique_actions"] = historique
    data["dernier_enrichissement"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    sauvegarder_memoire(data)
    
    return f"Mémoire enrichie avec métadonnées pour {len(journal)} échanges et {len(historique)} actions"


def _classer_moment_journee(heure: int) -> str:
    """Classifie le moment de la journée."""
    if 6 <= heure < 9:
        return "matin"
    elif 9 <= heure < 12:
        return "fin_matin"
    elif 12 <= heure < 14:
        return "midi"
    elif 14 <= heure < 18:
        return "apres_midi"
    elif 18 <= heure < 21:
        return "soiree"
    else:
        return "nuit"
