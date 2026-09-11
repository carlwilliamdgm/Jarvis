# syncsphere/__init__.py
"""Module SyncSphere - Sauvegarde locale chiffrée et synchronisation (GreatOS Module 7)."""
from syncsphere.snapshot import snapshot_manager

__all__ = ["snapshot_manager"]
