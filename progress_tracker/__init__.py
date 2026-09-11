# progress_tracker/__init__.py
"""Module Progress Tracker - Suivi des objectifs et métriques de progrès (GreatOS Module 5)."""
from progress_tracker.goals import goal_manager, Goal, GoalType, GoalStatus
from progress_tracker.analytics import calculer_statistiques_globales

__all__ = ["goal_manager", "Goal", "GoalType", "GoalStatus", "calculer_statistiques_globales"]
