"""Contextual Suggestions - Génération de suggestions intelligentes basées sur le contexte."""

from datetime import datetime, time
from typing import Dict, List, Any, Optional

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.pattern_analyzer import analyser_patterns_comportementaux, detecter_automatisations_potentielles
from capabilities import storage


def generer_suggestions_contextuelles() -> List[Dict[str, Any]]:
    """
    Génère des suggestions contextuelles intelligentes.
    
    Returns:
        Liste de suggestions avec leur pertinence et contexte.
    """
    data = normaliser_memoire(charger_memoire())
    suggestions = []
    
    # 1. Suggestions basées sur les patterns comportementaux
    suggestions.extend(_suggestions_patterns())
    
    # 2. Suggestions basées sur l'état système
    suggestions.extend(_suggestions_systeme())
    
    # 3. Suggestions basées sur l'heure actuelle
    suggestions.extend(_suggestions_temporelles())
    
    # 4. Suggestions basées sur le contexte utilisateur
    suggestions.extend(_suggestions_contexte_utilisateur(data))
    
    # 5. Suggestions basées sur les automatisations potentielles
    suggestions.extend(_suggestions_automatisations())
    
    # Trier par pertinence et limiter à 3 suggestions maximum
    suggestions = sorted(suggestions, key=lambda x: _priorite_suggestion(x), reverse=True)
    suggestions = suggestions[:3]
    
    return suggestions


def _suggestions_patterns() -> List[Dict[str, Any]]:
    """Génère des suggestions basées sur les patterns comportementaux."""
    suggestions = []
    patterns = analyser_patterns_comportementaux()
    
    # Suggérer une action fréquente à cette heure
    heure_actuelle = datetime.now().hour
    horaires = patterns.get("horaires", {})
    
    if horaires and heure_actuelle in horaires:
        actions = patterns.get("actions", {})
        if actions:
            action_top = max(actions, key=actions.get)
            suggestions.append({
                "type": "action_suggeree",
                "titre": f"Action habituelle à cette heure",
                "description": f"Vous exécutez souvent {action_top} à cette heure-ci.",
                "action": action_top,
                "pertinence": "moyenne",
                "raison": "pattern_horaire"
            })
    
    return suggestions


def _suggestions_systeme() -> List[Dict[str, Any]]:
    """Génère des suggestions basées sur l'état système."""
    suggestions = []
    
    try:
        stockage = storage.get_stockage()
        
        if stockage <= storage.SEUIL_ROUGE:
            suggestions.append({
                "type": "maintenance_systeme",
                "titre": "Stockage critique",
                "description": f"Espace disque très faible ({stockage}% libre). Nettoyage recommandé.",
                "action": "audit_stockage",
                "pertinence": "haute",
                "raison": "stockage_critique"
            })
        elif stockage <= storage.SEUIL_ORANGE:
            suggestions.append({
                "type": "maintenance_systeme",
                "titre": "Stockage faible",
                "description": f"Espace disque en alerte ({stockage}% libre). Surveillance recommandée.",
                "action": "top_fichiers_lourds",
                "pertinence": "moyenne",
                "raison": "stockage_faible"
            })
    except Exception:
        pass
    
    return suggestions


def _suggestions_temporelles() -> List[Dict[str, Any]]:
    """Génère des suggestions basées sur l'heure actuelle."""
    suggestions = []
    heure_actuelle = datetime.now().hour
    
    # Suggestions matinales
    if 6 <= heure_actuelle < 9:
        suggestions.append({
            "type": "suggestion_temporelle",
            "titre": "Routine matinale",
            "description": "Bon matin ! Souhaitez-vous un bilan des rappels et automatisations du jour ?",
            "action": "bilan_proactif",
            "pertinence": "moyenne",
            "raison": "matin"
        })
    
    # Suggestions de fin de journée
    elif 17 <= heure_actuelle < 20:
        suggestions.append({
            "type": "suggestion_temporelle",
            "titre": "Bilan de fin de journée",
            "description": "Fin de journée approche. Souhaitez-vous un résumé des activités ?",
            "action": "bilan_proactif",
            "pertinence": "moyenne",
            "raison": "fin_journee"
        })
    
    # Suggestions de nuit
    elif 22 <= heure_actuelle or heure_actuelle < 6:
        suggestions.append({
            "type": "suggestion_temporelle",
            "titre": "Mode nuit",
            "description": "Il est tard. Souhaitez-vous activer le mode silencieux pour les notifications ?",
            "action": "memoriser_preference",
            "pertinence": "basse",
            "raison": "nuit"
        })
    
    return suggestions


def _suggestions_contexte_utilisateur(data: Dict) -> List[Dict[str, Any]]:
    """Génère des suggestions basées sur le contexte utilisateur."""
    suggestions = []
    
    # Vérifier si des rappels sont dus
    from capabilities.scheduler import verifier_rappels
    rappels = verifier_rappels()
    
    if rappels and not rappels.startswith("Aucun"):
        suggestions.append({
            "type": "rappel_en_attente",
            "titre": "Rappels en attente",
            "description": "Vous avez des rappels qui nécessitent attention.",
            "action": "lire_rappels",
            "pertinence": "haute",
            "raison": "rappels"
        })
    
    # Vérifier si des automatisations sont dues
    from capabilities.scheduler import executer_automatisations_dues
    automatisations = executer_automatisations_dues()
    
    if automatisations and not automatisations.startswith("Aucune"):
        suggestions.append({
            "type": "automatisations_en_attente",
            "titre": "Automatisations en attente",
            "description": "Des automatisations sont prêtes à être exécutées.",
            "action": "executer_automatisations_dues",
            "pertinence": "haute",
            "raison": "automatisations"
        })
    
    # Vérifier si la mémoire est peu renseignée
    contexte = data.get("contexte", {})
    categories_vides = [cat for cat, contenu in contexte.items() if not contenu]
    
    if len(categories_vides) >= 4:
        suggestions.append({
            "type": "enrichissement_memoire",
            "titre": "Mémoire personnelle",
            "description": f"Votre profil est peu renseigné. Souhaitez-vous compléter vos informations ?",
            "action": "memoriser_contexte",
            "pertinence": "basse",
            "raison": "memoire_vide"
        })
    
    return suggestions


def _suggestions_automatisations() -> List[Dict[str, Any]]:
    """Génère des suggestions basées sur les automatisations potentielles."""
    suggestions = []
    
    automatisations_potentielles = detecter_automatisations_potentielles()
    
    for auto in automatisations_potentielles:
        if auto.get("pertinence") == "haute":
            suggestions.append({
                "type": "automatisation_suggeree",
                "titre": "Automatisation suggérée",
                "description": auto.get("suggestion", ""),
                "action": "ajouter_automatisation",
                "pertinence": "haute",
                "raison": "automatisation_potentielle",
                "details": auto
            })
    
    return suggestions


def _priorite_suggestion(suggestion: Dict) -> int:
    """Calcule la priorité d'une suggestion pour le tri."""
    pertinence_map = {
        "haute": 3,
        "moyenne": 2,
        "basse": 1
    }
    
    base = pertinence_map.get(suggestion.get("pertinence", "moyenne"), 2)
    
    # Bonus pour les suggestions de type système
    if suggestion.get("type") in ["maintenance_systeme", "rappel_en_attente", "automatisations_en_attente"]:
        base += 1
    
    return base


def formater_suggestions(suggestions: List[Dict]) -> str:
    """
    Formate les suggestions pour affichage utilisateur.
    
    Returns:
        Description textuelle des suggestions.
    """
    if not suggestions:
        return "Aucune suggestion contextuelle pour le moment."
    
    lignes = ["=== SUGGESTIONS INTELLIGENTES ==="]
    
    for i, suggestion in enumerate(suggestions, 1):
        pertinence_emoji = {
            "haute": "🔴",
            "moyenne": "🟡", 
            "basse": "🟢"
        }.get(suggestion.get("pertinence", "moyenne"), "🟡")
        
        lignes.append(f"\n{i}. {pertinence_emoji} {suggestion.get('titre', 'Suggestion')}")
        lignes.append(f"   {suggestion.get('description', '')}")
        
        if suggestion.get("action"):
            lignes.append(f"   Action suggérée : {suggestion['action']}")
    
    return "\n".join(lignes)


def enregistrer_suggestion_utilisee(suggestion: Dict, feedback: str) -> None:
    """
    Enregistre l'utilisation d'une suggestion avec feedback.
    
    Args:
        suggestion: La suggestion utilisée
        feedback: "positif", "negatif", "ignore"
    """
    data = normaliser_memoire(charger_memoire())
    
    feedback_suggestions = data.setdefault("feedback_suggestions", [])
    feedback_suggestions.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type_suggestion": suggestion.get("type"),
        "titre": suggestion.get("titre"),
        "feedback": feedback,
        "pertinence": suggestion.get("pertinence")
    })
    
    # Garder seulement les 100 derniers feedbacks
    data["feedback_suggestions"] = feedback_suggestions[-100:]
    
    sauvegarder_memoire(data)


def obtenir_statistiques_suggestions() -> str:
    """
    Retourne des statistiques sur l'utilisation des suggestions.
    
    Returns:
        Description textuelle des statistiques.
    """
    data = charger_memoire()
    feedback = data.get("feedback_suggestions", [])
    
    if not feedback:
        return "Aucune donnée de feedback sur les suggestions pour le moment."
    
    total = len(feedback)
    positifs = sum(1 for f in feedback if f.get("feedback") == "positif")
    negatifs = sum(1 for f in feedback if f.get("feedback") == "negatif")
    ignores = sum(1 for f in feedback if f.get("feedback") == "ignore")
    
    # Analyser par type
    par_type = {}
    for f in feedback:
        type_s = f.get("type_suggestion", "inconnu")
        if type_s not in par_type:
            par_type[type_s] = {"total": 0, "positifs": 0}
        par_type[type_s]["total"] += 1
        if f.get("feedback") == "positif":
            par_type[type_s]["positifs"] += 1
    
    lignes = ["=== STATISTIQUES SUGGESTIONS ==="]
    lignes.append(f"Total suggestions : {total}")
    lignes.append(f"Feedback positif : {positifs} ({positifs/total*100:.1f}%)")
    lignes.append(f"Feedback négatif : {negatifs} ({negatifs/total*100:.1f}%)")
    lignes.append(f"Ignorées : {ignores} ({ignores/total*100:.1f}%)")
    
    lignes.append("\nPar type de suggestion :")
    for type_s, stats in sorted(par_type.items(), key=lambda x: -x[1]["total"]):
        taux = stats["positifs"] / stats["total"] * 100 if stats["total"] > 0 else 0
        lignes.append(f"  {type_s} : {stats['total']} suggestions, {taux:.1f}% positif")
    
    return "\n".join(lignes)
