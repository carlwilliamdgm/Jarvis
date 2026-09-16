# progress_tracker/tools.py
"""Outils et façades publiques de capacités pour le module Progress Tracker (GreatOS Module 5)."""

from __future__ import annotations

from datashield.error_classification import resultat_erreur
from progress_tracker.analytics import calculer_statistiques_globales
from progress_tracker.goals import goal_manager


def creer_objectif_tool(id_obj: str, titre: str, description: str = "", cible: float = 100.0, unite: str = "%") -> str:
    """Crée un nouvel objectif personnel ou professionnel dans le Progress Tracker."""
    try:
        g = goal_manager.creer_objectif(id_obj=id_obj, titre=titre, description=description, cible=cible, unite=unite)
        return f"Objectif créé avec succès : [{g.id}] {g.titre} (Cible : {g.cible_valeur} {g.unite})"
    except Exception as e:
        return resultat_erreur(f"Erreur création objectif : {e}", e)


def lister_objectifs_tool() -> str:
    """Liste tous les objectifs suivis dans GreatOS avec leur progression."""
    try:
        objectifs = goal_manager.lister_objectifs()
        if not objectifs:
            return "Aucun objectif enregistré pour le moment."
        lignes = ["=== OBJECTIFS GREATOS ==="]
        for g in objectifs:
            lignes.append(f"- [{g.status.value.upper()}] {g.titre} ({g.id}) : {g.valeur_actuelle}/{g.cible_valeur} {g.unite} ({g.progression_pourcentage:.1f}%)")
        return "\n".join(lignes)
    except Exception as e:
        return resultat_erreur(f"Erreur liste objectifs : {e}", e)


def mettre_a_jour_objectif_tool(id_obj: str, nouvelle_valeur: float) -> str:
    """Met à jour la valeur actuelle d'un objectif pour recalculer sa progression."""
    try:
        g = goal_manager.mettre_a_jour_progression(id_obj, float(nouvelle_valeur))
        if not g:
            return f"Objectif introuvable : {id_obj}"
        return f"Objectif [{g.id}] mis à jour : {g.valeur_actuelle}/{g.cible_valeur} {g.unite} ({g.progression_pourcentage:.1f}%) - Statut : {g.status.value}"
    except Exception as e:
        return resultat_erreur(f"Erreur mise à jour objectif : {e}", e)


def stats_objectifs_tool() -> str:
    """Calcule et affiche les statistiques globales des objectifs suivis."""
    try:
        stats = calculer_statistiques_globales()
        return (
            f"=== STATISTIQUES PROGRESS TRACKER ===\n"
            f"Total : {stats['total']} | Actifs : {stats['actifs']} | Terminés : {stats['termines']}\n"
            f"Taux de complétion : {stats['taux_completion']}%\n"
            f"Progression moyenne : {stats['progression_moyenne']}%"
        )
    except Exception as e:
        return resultat_erreur(f"Erreur calcul statistiques objectifs : {e}", e)

