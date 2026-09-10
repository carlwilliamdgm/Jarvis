"""Decision Analyzer - Auto-réflexion et analyse des décisions."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from context_engine.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from datashield.error_classification import CATEGORIES_ERREUR


def analyser_decisions_recentes(jours: int = 7) -> Dict[str, Any]:
    """
    Analyse les décisions récentes pour identifier les patterns de succès/échec.
    
    Args:
        jours: Nombre de jours à analyser
        
    Returns:
        Analyse des décisions et patterns détectés
    """
    data = normaliser_memoire(charger_memoire())
    historique = data.get("historique_actions", [])
    erreurs = data.get("erreurs_systeme", {})
    
    # Filtrer les données récentes
    date_limite = datetime.now() - timedelta(days=jours)
    actions_recentes = []
    
    for action in historique:
        try:
            date_str = action.get("date", "")
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                if dt >= date_limite:
                    actions_recentes.append(action)
        except (ValueError, TypeError):
            continue
    
    # Analyser les outils les plus utilisés
    outils_utilises = Counter([a.get("outil", "") for a in actions_recentes])
    
    # Analyser les résultats (succès/échec)
    succes = 0
    echecs = 0
    erreurs_par_outil = defaultdict(int)
    
    for action in actions_recentes:
        resultat = action.get("resultat", "").lower()
        if "erreur" in resultat or "failed" in resultat or "exception" in resultat:
            echecs += 1
            erreurs_par_outil[action.get("outil", "")] += 1
        else:
            succes += 1
    
    # Analyser les catégories d'erreurs
    categories_erreurs = {}
    for categorie, liste_erreurs in erreurs.items():
        erreurs_recentes = []
        for erreur in liste_erreurs:
            try:
                date_str = erreur.get("date", "")
                if date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    if dt >= date_limite:
                        erreurs_recentes.append(erreur)
            except (ValueError, TypeError):
                continue
        if erreurs_recentes:
            categories_erreurs[categorie] = len(erreurs_recentes)
    
    return {
        "periode_analysee": f"{jours} jours",
        "total_actions": len(actions_recentes),
        "succes": succes,
        "echecs": echecs,
        "taux_succes": round(succes / len(actions_recentes) * 100, 1) if actions_recentes else 0,
        "outils_top": dict(outils_utilises.most_common(5)),
        "erreurs_par_outil": dict(erreurs_par_outil),
        "categories_erreurs": categories_erreurs,
        "timestamp_analyse": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def detecter_patterns_erreur() -> List[Dict[str, Any]]:
    """
    Détecte les patterns d'erreur récurrents.
    
    Returns:
        Liste des patterns d'erreur détectés avec suggestions de correction
    """
    data = normaliser_memoire(charger_memoire())
    erreurs = data.get("erreurs_systeme", {})
    
    patterns = []
    
    # Analyser chaque catégorie d'erreurs
    for categorie, liste_erreurs in erreurs.items():
        if not liste_erreurs:
            continue
        
        # Regrouper par code d'erreur
        codes = defaultdict(list)
        for erreur in liste_erreurs:
            code = erreur.get("code_brut", "inconnu")
            codes[code].append(erreur)
        
        # Détecter les codes récurrents
        for code, occurrences in codes.items():
            if len(occurrences) >= 3:
                patterns.append({
                    "categorie": categorie,
                    "code": code,
                    "frequence": len(occurrences),
                    "derniere_occurrence": occurrences[-1].get("date", ""),
                    "suggestion": _generer_suggestion_correction(categorie, code, occurrences)
                })
    
    # Trier par fréquence
    patterns.sort(key=lambda x: x["frequence"], reverse=True)
    
    return patterns[:10]


def _generer_suggestion_correction(categorie: str, code: str, occurrences: List[Dict]) -> str:
    """Génère une suggestion de correction basée sur le pattern d'erreur."""
    suggestions = {
        "permission_denied": "Vérifiez les permissions de fichier/dossier",
        "file_not_found": "Vérifiez que le chemin d'accès est correct",
        "timeout": "Augmentez le délai d'attente ou vérifiez la connexion réseau",
        "memory_error": "Libérez de la mémoire ou réduisez la charge de travail",
        "network_error": "Vérifiez votre connexion internet",
        "api_error": "Vérifiez les clés API et les quotas",
    }
    
    # Suggestions basées sur le code
    code_str = str(code).lower()
    for pattern, suggestion in suggestions.items():
        if pattern in code_str:
            return suggestion
    
    # Suggestion générique basée sur la catégorie
    if categorie == "fichier":
        return "Vérifiez les chemins d'accès et les permissions"
    elif categorie == "reseau":
        return "Vérifiez la connectivité et les configurations réseau"
    elif categorie == "permission":
        return "Exécutez avec les droits appropriés"
    else:
        return "Consultez la documentation pour résoudre ce problème"


def memoriser_succes(outil: str, args: Dict, contexte: str) -> None:
    """
    Mémorise une solution réussie pour réutilisation future.
    
    Args:
        outil: L'outil utilisé
        args: Les arguments utilisés
        contexte: Le contexte du succès
    """
    data = normaliser_memoire(charger_memoire())
    
    succes = data.setdefault("apprentissage_succes", [])
    succes.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "outil": outil,
        "args": args,
        "contexte": contexte,
        "utilisations": 1
    })
    
    # Garder seulement les 200 derniers succès
    data["apprentissage_succes"] = succes[-200:]
    
    sauvegarder_memoire(data)


def rechercher_solution_similaire(outil: str, contexte: str) -> Optional[Dict[str, Any]]:
    """
    Recherche une solution similaire dans l'historique des succès.
    
    Args:
        outil: L'outil concerné
        contexte: Le contexte actuel
        
    Returns:
        Solution similaire trouvée ou None
    """
    data = charger_memoire()
    succes = data.get("apprentissage_succes", [])
    
    # Chercher les succès avec le même outil
    solutions_similaires = []
    for s in succes:
        if s.get("outil") == outil:
            # Calculer la similarité du contexte
            similarite = _calculer_similarite_contexte(contexte, s.get("contexte", ""))
            if similarite > 0.5:  # Seuil de similarité
                solutions_similaires.append({
                    **s,
                    "similarite": similarite
                })
    
    # Retourner la solution la plus similaire
    if solutions_similaires:
        solutions_similaires.sort(key=lambda x: x["similarite"], reverse=True)
        return solutions_similaires[0]
    
    return None


def _calculer_similarite_contexte(contexte1: str, contexte2: str) -> float:
    """Calcule la similarité entre deux contextes (simplifié)."""
    mots1 = set(contexte1.lower().split())
    mots2 = set(contexte2.lower().split())
    
    if not mots1 or not mots2:
        return 0.0
    
    intersection = mots1.intersection(mots2)
    union = mots1.union(mots2)
    
    return len(intersection) / len(union) if union else 0.0


def ajuster_strategies(analyse: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Génère des ajustements de stratégie basés sur l'analyse.
    
    Args:
        analyse: L'analyse des décisions
        
    Returns:
        Liste d'ajustements suggérés
    """
    ajustements = []
    
    taux_succes = analyse.get("taux_succes", 0)
    
    # Si le taux de succès est faible
    if taux_succes < 70:
        ajustements.append({
            "type": "amelioration_globale",
            "priorite": "haute",
            "suggestion": f"Taux de succès faible ({taux_succes}%). Envisagez de revoir les stratégies actuelles.",
            "action": "analyser_patterns_erreur"
        })
    
    # Si certains outils ont beaucoup d'erreurs
    erreurs_par_outil = analyse.get("erreurs_par_outil", {})
    for outil, count in erreurs_par_outil.items():
        if count >= 3:
            ajustements.append({
                "type": "optimisation_outil",
                "priorite": "moyenne",
                "suggestion": f"L'outil {outil} a {count} erreurs récentes. Vérifiez son utilisation.",
                "action": f"revoir_utilisation_{outil}"
            })
    
    # Si certaines catégories d'erreurs sont fréquentes
    categories_erreurs = analyse.get("categories_erreurs", {})
    for categorie, count in categories_erreurs.items():
        if count >= 5:
            ajustements.append({
                "type": "categorie_erreur",
                "priorite": "moyenne",
                "suggestion": f"La catégorie d'erreur {categorie} est fréquente ({count} occurrences).",
                "action": f"analyser_categorie_{categorie}"
            })
    
    return ajustements


def generer_rapport_performance() -> str:
    """
    Génère un rapport de performance complet.
    
    Returns:
        Description textuelle de la performance
    """
    analyse = analyser_decisions_recentes(7)
    patterns_erreur = detecter_patterns_erreur()
    ajustements = ajuster_strategies(analyse)
    
    lignes = ["=== RAPPORT PERFORMANCE JARVIS ==="]
    lignes.append(f"Période analysée : {analyse['periode_analysee']}")
    lignes.append(f"Actions totales : {analyse['total_actions']}")
    lignes.append(f"Succès : {analyse['succes']} ({analyse['taux_succes']}%)")
    lignes.append(f"Échecs : {analyse['echecs']}")
    
    # Outils les plus utilisés
    lignes.append("\nOutils les plus utilisés :")
    for outil, count in list(analyse.get("outils_top", {}).items())[:5]:
        lignes.append(f"  {outil} : {count} fois")
    
    # Patterns d'erreur
    if patterns_erreur:
        lignes.append(f"\n⚠️  PATTERNS D'ERREUR DÉTECTÉS ({len(patterns_erreur)}) :")
        for pattern in patterns_erreur[:5]:
            lignes.append(f"  {pattern['categorie']} - {pattern['code']} ({pattern['frequence']}x)")
            lignes.append(f"    Suggestion : {pattern['suggestion']}")
    else:
        lignes.append("\n✅ Aucun pattern d'erreur détecté")
    
    # Ajustements suggérés
    if ajustements:
        lignes.append(f"\n💡 AJUSTEMENTS SUGGÉRÉS ({len(ajustements)}) :")
        for ajustement in ajustements[:3]:
            priorite_emoji = {"haute": "🔴", "moyenne": "🟡", "basse": "🟢"}.get(ajustement.get("priorite"), "🟡")
            lignes.append(f"  {priorite_emoji} {ajustement['suggestion']}")
    
    lignes.append(f"\nRapport généré : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(lignes)


def enregistrer_apprentissage(type_apprentissage: str, contenu: str, contexte: str = "") -> None:
    """
    Enregistre un apprentissage pour amélioration future.
    
    Args:
        type_apprentissage: Type d'apprentissage (succes, echec, pattern, optimisation)
        contenu: Contenu de l'apprentissage
        contexte: Contexte de l'apprentissage
    """
    data = normaliser_memoire(charger_memoire())
    
    apprentissages = data.setdefault("apprentissages", [])
    apprentissages.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": type_apprentissage,
        "contenu": contenu,
        "contexte": contexte
    })
    
    # Garder seulement les 500 derniers apprentissages
    data["apprentissages"] = apprentissages[-500:]
    
    sauvegarder_memoire(data)


def obtenir_insights_apprentissage() -> str:
    """
    Obtient des insights basés sur les apprentissages enregistrés.
    
    Returns:
        Description textuelle des insights
    """
    data = charger_memoire()
    apprentissages = data.get("apprentissages", [])
    
    if not apprentissages:
        return "Aucun apprentissage enregistré pour le moment."
    
    # Analyser par type
    par_type = defaultdict(int)
    for app in apprentissages:
        par_type[app.get("type", "inconnu")] += 1
    
    # Apprentissages récents
    recents = apprentissages[-10:]
    
    lignes = ["=== INSIGHTS APPRENTISSAGE ==="]
    lignes.append(f"Total apprentissages : {len(apprentissages)}")
    
    lignes.append("\nPar type :")
    for type_app, count in sorted(par_type.items(), key=lambda x: -x[1]):
        lignes.append(f"  {type_app} : {count}")
    
    lignes.append("\nApprentissages récents :")
    for app in reversed(recents):
        type_emoji = {
            "succes": "✅",
            "echec": "❌",
            "pattern": "🔍",
            "optimisation": "⚡"
        }.get(app.get("type"), "📝")
        
        lignes.append(f"  {type_emoji} {app.get('contenu', '')[:80]}")
        lignes.append(f"    {app.get('date', '')}")
    
    return "\n".join(lignes)
