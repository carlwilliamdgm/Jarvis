"""Personality Manager - Gestion et adaptation de la personnalité Jarvis."""

from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict

from context_engine.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


# Traits de personnalité de base Jarvis
PERSONNALITE_BASE = {
    "sarcasme": 0.3,        # Niveau de sarcasme (0-1)
    "formalite": 0.4,       # Niveau de formalité (0-1)
    "proactivite": 0.7,     # Niveau de proactivité (0-1)
    "humour": 0.4,          # Niveau d'humour (0-1)
    "empathie": 0.6,        # Niveau d'empathie (0-1)
    "concision": 0.5,       # Niveau de concision (0-1)
    "creativite": 0.5,      # Niveau de créativité (0-1)
}


def obtenir_personnalite_actuelle() -> Dict[str, float]:
    """
    Obtient la personnalité actuelle de Jarvis.
    
    Returns:
        Dict des traits de personnalité avec leurs valeurs
    """
    data = charger_memoire()
    personnalite = data.get("personnalite", {})
    
    # Fusionner avec la personnalité de base
    personnalite_complete = PERSONNALITE_BASE.copy()
    personnalite_complete.update(personnalite)
    
    return personnalite_complete


def ajuster_personnalite(trait: str, delta: float) -> Dict[str, float]:
    """
    Ajuste un trait de personnalité.
    
    Args:
        trait: Le trait à ajuster
        delta: La variation (-1 à 1)
        
    Returns:
        La nouvelle personnalité
    """
    if trait not in PERSONNALITE_BASE:
        raise ValueError(f"Trait inconnu: {trait}")
    
    data = normaliser_memoire(charger_memoire())
    personnalite = data.setdefault("personnalite", PERSONNALITE_BASE.copy())
    
    # Ajuster le trait avec bornes [0, 1]
    valeur_actuelle = personnalite.get(trait, PERSONNALITE_BASE[trait])
    nouvelle_valeur = max(0.0, min(1.0, valeur_actuelle + delta))
    personnalite[trait] = nouvelle_valeur
    
    # Enregistrer l'ajustement
    ajustements = data.setdefault("ajustements_personnalite", [])
    ajustements.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trait": trait,
        "ancienne_valeur": valeur_actuelle,
        "nouvelle_valeur": nouvelle_valeur,
        "delta": delta
    })
    
    # Garder seulement les 100 derniers ajustements
    data["ajustements_personnalite"] = ajustements[-100:]
    
    sauvegarder_memoire(data)
    
    return personnalite


def adapter_ton_contextuel(message_utilisateur: str) -> str:
    """
    Adapte le ton de réponse en fonction du contexte et de l'humeur détectée.
    
    Args:
        message_utilisateur: Le message de l'utilisateur
        
    Returns:
        Instruction de ton pour le LLM
    """
    personnalite = obtenir_personnalite_actuelle()
    
    # Détecter l'humeur dans le message
    message_lower = message_utilisateur.lower()
    
    # Indices d'urgence/stress
    mots_urgence = ["urgent", "vite", "immédiatement", "maintenant", "help", "problème"]
    if any(mot in message_lower for mot in mots_urgence):
        return "Ton direct et concis, priorité à l'efficacité"
    
    # Indices de frustration/colère
    mots_frustration = ["frustrant", "énervant", "pas marche", "erreur", "échec"]
    if any(mot in message_lower for mot in mots_frustration):
        return "Ton empathique et constructif, éviter l'humour"
    
    # Indices de détente/positivité
    mots_positifs = ["super", "génial", "merci", "parfait", "excellent"]
    if any(mot in message_lower for mot in mots_positifs):
        return "Ton chaleureux et engageant, humour approprié"
    
    # Adaptation basée sur la personnalité
    instructions = []
    
    if personnalite["sarcasme"] > 0.6:
        instructions.append("sarcasme léger approprié")
    elif personnalite["sarcasme"] < 0.2:
        instructions.append("pas de sarcasme")
    
    if personnalite["formalite"] > 0.7:
        instructions.append("ton formel et poli")
    elif personnalite["formalite"] < 0.3:
        instructions.append("ton décontracté")
    
    if personnalite["humour"] > 0.6:
        instructions.append("humour quand approprié")
    
    if personnalite["concision"] > 0.7:
        instructions.append("réponses concises")
    
    return ", ".join(instructions) if instructions else "ton naturel et équilibré"


def memoriser_preference_communication(type_interaction: str, feedback: str) -> None:
    """
    Mémorise une préférence de communication de l'utilisateur.
    
    Args:
        type_interaction: Type d'interaction (ton, style, format)
        feedback: Feedback de l'utilisateur (positif/négatif)
    """
    data = normaliser_memoire(charger_memoire())
    
    preferences = data.setdefault("preferences_communication", defaultdict(int))
    preferences[f"{type_interaction}_{feedback}"] += 1
    
    data["preferences_communication"] = dict(preferences)
    sauvegarder_memoire(data)


def analyser_preferences_communication() -> Dict[str, Any]:
    """
    Analyse les préférences de communication accumulées.
    
    Returns:
        Analyse des préférences détectées
    """
    data = charger_memoire()
    preferences = data.get("preferences_communication", {})
    
    analyse = {
        "ton_prefere": "equilibré",
        "style_prefere": "standard",
        "confiance": 0.5
    }
    
    # Analyser les préférences de ton
    ton_positif = sum(v for k, v in preferences.items() if "ton_positif" in k)
    ton_negatif = sum(v for k, v in preferences.items() if "ton_negatif" in k)
    
    if ton_positif > ton_negatif * 1.5:
        analyse["ton_prefere"] = "actuel"
    elif ton_negatif > ton_positif * 1.5:
        analyse["ton_prefere"] = "ajuster"
    
    # Calculer la confiance
    total_feedback = sum(preferences.values())
    if total_feedback > 0:
        positif_total = sum(v for k, v in preferences.items() if "positif" in k)
        analyse["confiance"] = positif_total / total_feedback
    
    return analyse


def generer_prompt_personnalite() -> str:
    """
    Génère un prompt de personnalité pour le LLM.
    
    Returns:
        Instructions de personnalité
    """
    personnalite = obtenir_personnalite_actuelle()
    
    lignes = ["Instructions de personnalité :"]
    
    # Sarcasme
    if personnalite["sarcasme"] > 0.7:
        lignes.append("- Sarcasme britannique élégant et occasionnel")
    elif personnalite["sarcasme"] > 0.4:
        lignes.append("- Léger sarcasme quand approprié")
    else:
        lignes.append("- Sincère et direct, éviter le sarcasme")
    
    # Formalité
    if personnalite["formalite"] > 0.7:
        lignes.append("- Ton formel et professionnel")
    elif personnalite["formalite"] < 0.3:
        lignes.append("- Ton décontracté et amical")
    else:
        lignes.append("- Ton poli mais accessible")
    
    # Proactivité
    if personnalite["proactivite"] > 0.7:
        lignes.append("- Très proactif, anticiper les besoins")
    elif personnalite["proactivite"] < 0.3:
        lignes.append("- Répondre uniquement aux demandes explicites")
    
    # Humour
    if personnalite["humour"] > 0.6:
        lignes.append("- Humour et références culturelles quand approprié")
    
    # Empathie
    if personnalite["empathie"] > 0.7:
        lignes.append("- Très empathique, comprendre le contexte émotionnel")
    
    # Concision
    if personnalite["concision"] > 0.7:
        lignes.append("- Réponses concises et directes")
    
    return "\n".join(lignes)


def evoluer_personnalite() -> Dict[str, float]:
    """
    Fait évoluer la personnalité basée sur les interactions passées.
    
    Returns:
        Nouvelle personnalité après évolution
    """
    data = charger_memoire()
    ajustements = data.get("ajustements_personnalite", [])
    preferences = data.get("preferences_communication", {})
    
    personnalite = obtenir_personnalite_actuelle()
    
    # Évolution basée sur les ajustements récents
    ajustements_recents = [a for a in ajustements if datetime.strptime(a["date"], "%Y-%m-%d %H:%M:%S") > datetime.now() - timedelta(days=7)]
    
    # Si beaucoup d'ajustements récents sur un trait, stabiliser
    par_trait = defaultdict(list)
    for a in ajustements_recents:
        par_trait[a["trait"]].append(a["delta"])
    
    for trait, deltas in par_trait.items():
        if len(deltas) > 5:
            # Stabiliser en réduisant la sensibilité
            moyenne = sum(deltas) / len(deltas)
            if abs(moyenne) < 0.1:
                # Tendance à la stabilité, réduire le trait
                personnalite[trait] = personnalite[trait] * 0.95
    
    # Évolution basée sur les préférences utilisateur
    analyse_prefs = analyser_preferences_communication()
    
    if analyse_prefs["ton_prefere"] == "actuel":
        # Renforcer la personnalité actuelle
        personnalite["sarcasme"] = min(1.0, personnalite["sarcasme"] * 1.05)
    elif analyse_prefs["ton_prefere"] == "ajuster":
        # Adoucir la personnalité
        personnalite["sarcasme"] = max(0.0, personnalite["sarcasme"] * 0.95)
    
    # Sauvegarder la personnalité évoluée
    data["personnalite"] = personnalite
    sauvegarder_memoire(data)
    
    return personnalite


def obtenir_rapport_personnalite() -> str:
    """
    Génère un rapport de personnalité.
    
    Returns:
        Description textuelle de la personnalité actuelle
    """
    personnalite = obtenir_personnalite_actuelle()
    ajustements = charger_memoire().get("ajustements_personnalite", [])
    preferences = analyser_preferences_communication()
    
    lignes = ["=== RAPPORT PERSONNALITÉ ==="]
    
    # Traits actuels
    lignes.append("\nTraits actuels :")
    for trait, valeur in sorted(personnalite.items()):
        barre = "█" * int(valeur * 10) + "░" * (10 - int(valeur * 10))
        lignes.append(f"  {trait:12} : {barre} {valeur:.2f}")
    
    # Ajustements récents
    if ajustements:
        lignes.append(f"\nAjustements récents ({len(ajustements)}) :")
        for a in ajustements[-5:]:
            direction = "↑" if a["delta"] > 0 else "↓"
            lignes.append(f"  {a['date']} : {a['trait']} {direction} {abs(a['delta']):.2f}")
    
    # Préférences utilisateur
    lignes.append("\nPréférences utilisateur :")
    lignes.append(f"  Ton préféré : {preferences['ton_prefere']}")
    lignes.append(f"  Style préféré : {preferences['style_prefere']}")
    lignes.append(f"  Confiance : {preferences['confiance']:.1%}")
    
    return "\n".join(lignes)


def reinitialiser_personnalite() -> Dict[str, float]:
    """
    Réinitialise la personnalité aux valeurs de base.
    
    Returns:
        Personnalité réinitialisée
    """
    data = normaliser_memoire(charger_memoire())
    data["personnalite"] = PERSONNALITE_BASE.copy()
    sauvegarder_memoire(data)
    
    return PERSONNALITE_BASE.copy()
