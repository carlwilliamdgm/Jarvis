"""Coordination file for concurrent Stark sessions."""

from __future__ import annotations

import json
import os
from datetime import datetime

import psutil

from core_intellect.paths import JARVIS_DIR

STARK_ACTIF_PATH = JARVIS_DIR / "stark_actif.json"


def verifier_instances_stark() -> list[dict]:
    """Return live Stark instances and silently prune dead/corrupt entries."""
    entrees = _lire_instances()
    if not entrees:
        return []

    actives = []
    for entree in entrees:
        if _instance_est_active(entree):
            actives.append(entree)

    if actives != entrees:
        _ecrire_instances(actives)

    return actives


def enregistrer_instance_stark(objectif: str) -> None:
    """Register the current process as an active Stark instance."""
    instances = verifier_instances_stark()
    pid = os.getpid()
    nom_process = _nom_process(pid)
    instances = [instance for instance in instances if instance.get("pid") != pid]
    instances.append({
        "pid": pid,
        "nom_process": nom_process,
        "lance_le": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "objectif": objectif,
    })
    _ecrire_instances(instances)


def retirer_instance_stark() -> None:
    """Remove the current process from the coordination file."""
    pid = os.getpid()
    instances = _lire_instances()
    restantes = [instance for instance in instances if instance.get("pid") != pid]
    _ecrire_instances(restantes)


def _lire_instances() -> list[dict]:
    try:
        if not STARK_ACTIF_PATH.exists():
            return []
        data = json.loads(STARK_ACTIF_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [entree for entree in data if isinstance(entree, dict)]
    except Exception:
        return []


def _ecrire_instances(instances: list[dict]) -> None:
    try:
        STARK_ACTIF_PATH.write_text(
            json.dumps(instances, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _instance_est_active(entree: dict) -> bool:
    try:
        pid = int(entree.get("pid"))
        nom_process = str(entree.get("nom_process") or "")
        if not psutil.pid_exists(pid):
            return False
        return _nom_process(pid) == nom_process
    except Exception:
        return False


def _nom_process(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""
