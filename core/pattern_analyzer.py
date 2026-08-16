"""Pattern Analyzer - Détection et analyse des patterns comportementaux."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def analyser_patterns_comportementaux() -> Dict[str, Any]:
    """
    Analyse les patterns comportementaux à partir de l'historique.
    
    Returns:
        Dict contenant les patterns détectés :
        - horaires: heures fréquentes d'utilisation
        - actions: actions répétitives
        - sequences: séquences d'actions courantes
        - frequence: fréquence des patterns
    """
    data = normaliser_memoire(charger_memoire())
    historique = data.get("historique_actions", [])
    journal = data.get("journal_conversation", [])
    
    patterns = {
        "horaires": _analyser_horaires(historique, journal),
        "actions": _analyser_actions_repetitives(historique),
        "sequences": _analyser_sequences_actions(historique),
        "frequence": _analyser_frequence_globale(historique, journal),
        "date_analyse": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Sauvegarder les patterns dans la mémoire
    data["patterns_comportementaux"] = patterns
    sauvegarder_memoire(data)
    
    return patterns


def _analyser_horaires(historique: List[Dict], journal: List[Dict]) -> Dict[str, int]:
    """Analyse les horaires d'utilisation."""
    heures = []
    
    # Extraire les heures de l'historique d'actions
    for action in historique:
        try:
            date_str = action.get("date", "")
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                heures.append(dt.hour)
        except (ValueError, TypeError):
            continue
    
    # Extraire les heures du journal de conversation
    for echange in journal:
        try:
            date_str = echange.get("date", "")
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                heures.append(dt.hour)
        except (ValueError, TypeError):
            continue
    
    # Compter les fréquences par heure
    compteur = Counter(heures)
    
    # Retourner les top 5 heures les plus fréquentes
    return dict(compteur.most_common(5))


def _analyser_actions_repetitives(historique: List[Dict]) -> Dict[str, int]:
    """Analyse les actions répétitives."""
    actions = [action.get("outil", "") for action in historique if action.get("outil")]
    compteur = Counter(actions)
    
    # Retourner les top 10 actions les plus fréquentes
    return dict(compteur.most_common(10))


def _analyser_sequences_actions(historique: List[Dict]) -> List[Dict[str, Any]]:
    """Analyse les séquences d'actions courantes."""
    if len(historique) < 3:
        return []
    
    sequences = []
    sequence_length = 3
    
    # Extraire les séquences d'actions
    for i in range(len(historique) - sequence_length + 1):
        sequence = tuple(
            historique[i + j].get("outil", "") 
            for j in range(sequence_length)
        )
        sequences.append(sequence)
    
    # Compter les fréquences des séquences
    compteur = Counter(sequences)
    
    # Retourner les top 5 séquences les plus fréquentes
    resultats = []
    for sequence, count in compteur.most_common(5):
        resultats.append({
            "sequence": list(sequence),
            "frequence": count
        })
    
    return resultats


def _analyser_frequence_globale(historique: List[Dict], journal: List[Dict]) -> Dict[str, int]:
    """Analyse la fréquence globale d'utilisation."""
    total_actions = len(historique)
    total_echanges = len(journal)
    
    # Calculer la fréquence par jour sur les 7 derniers jours
    date_limite = datetime.now() - timedelta(days=7)
    
    actions_recentes = 0
    echanges_recents = 0
    
    for action in historique:
        try:
            date_str = action.get("date", "")
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                if dt >= date_limite:
                    actions_recentes += 1
        except (ValueError, TypeError):
            continue
    
    for echange in journal:
        try:
            date_str = echange.get("date", "")
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                if dt >= date_limite:
                    echanges_recents += 1
        except (ValueError, TypeError):
            continue
    
    return {
        "total_actions": total_actions,
        "total_echanges": total_echanges,
        "actions_7_jours": actions_recentes,
        "echanges_7_jours": echanges_recents,
        "moyenne_actions_jour": actions_recentes / 7 if actions_recentes > 0 else 0,
        "moyenne_echanges_jour": echanges_recents / 7 if echanges_recents > 0 else 0
    }


def detecter_automatisations_potentielles() -> List[Dict[str, Any]]:
    """
    Détecte des automatisations potentielles basées sur les patterns.
    
    Returns:
        Liste d'automatisations suggérées avec leur pertinence.
    """
    patterns = analyser_patterns_comportementaux()
    suggestions = []
    
    # Analyser les actions répétitives
    actions_repetitives = patterns.get("actions", {})
    for outil, frequence in actions_repetitives.items():
        if frequence >= 5:  # Seuil de répétition
            suggestions.append({
                "type": "automatisation_action",
                "outil": outil,
                "frequence": frequence,
                "pertinence": "haute" if frequence >= 10 else "moyenne",
                "suggestion": f"Créer une automatisation pour {outil} (exécuté {frequence} fois)"
            })
    
    # Analyser les séquences
    sequences = patterns.get("sequences", [])
    for seq_data in sequences:
        if seq_data["frequence"] >= 3:  # Seuil de répétition
            suggestions.append({
                "type": "automatisation_sequence",
                "sequence": seq_data["sequence"],
                "frequence": seq_data["frequence"],
                "pertinence": "haute" if seq_data["frequence"] >= 5 else "moyenne",
                "suggestion": f"Créer une automatisation pour la séquence {' -> '.join(seq_data['sequence'])}"
            })
    
    # Analyser les horaires
    horaires = patterns.get("horaires", {})
    if horaires:
        heure_top = max(horaires, key=horaires.get)
        suggestions.append({
            "type": "automatisation_horaire",
            "heure": heure_top,
            "frequence": horaires[heure_top],
            "pertinence": "moyenne",
            "suggestion": f"Optimiser les automatisations pour {heure_top}h (heure la plus active)"
        })
    
    return suggestions


def obtenir_patterns_actuels() -> str:
    """
    Retourne une description lisible des patterns actuels.
    
    Returns:
        Description textuelle des patterns détectés.
    """
    data = charger_memoire()
    patterns = data.get("patterns_comportementaux", {})
    
    if not patterns:
        return "Aucun pattern comportemental détecté pour le moment."
    
    lignes = ["=== PATTERNS COMPORTEMENTAUX ==="]
    lignes.append(f"Analyse du : {patterns.get('date_analyse', 'inconnue')}")
    
    # Horaires
    horaires = patterns.get("horaires", {})
    if horaires:
        lignes.append("\nHoraires les plus actifs :")
        for heure, count in sorted(horaires.items()):
            lignes.append(f"  {heure}h : {count} interactions")
    
    # Actions répétitives
    actions = patterns.get("actions", {})
    if actions:
        lignes.append("\nActions les plus fréquentes :")
        for outil, count in sorted(actions.items(), key=lambda x: -x[1])[:5]:
            lignes.append(f"  {outil} : {count} exécutions")
    
    # Séquences
    sequences = patterns.get("sequences", [])
    if sequences:
        lignes.append("\nSéquences d'actions courantes :")
        for seq in sequences[:3]:
            lignes.append(f"  {' -> '.join(seq['sequence'])} : {seq['frequence']} fois")
    
    # Fréquence
    frequence = patterns.get("frequence", {})
    if frequence:
        lignes.append("\nStatistiques d'utilisation :")
        lignes.append(f"  Total actions : {frequence.get('total_actions', 0)}")
        lignes.append(f"  Total échanges : {frequence.get('total_echanges', 0)}")
        lignes.append(f"  Actions/jour (7j) : {frequence.get('moyenne_actions_jour', 0):.1f}")
        lignes.append(f"  Échanges/jour (7j) : {frequence.get('moyenne_echanges_jour', 0):.1f}")
    
    return "\n".join(lignes)
