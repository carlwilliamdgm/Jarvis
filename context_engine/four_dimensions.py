"""Context Engine - Conscience Contextuelle Quadridimensionnelle (CDC GreatOS Module 4.3).

Capture et analyse l'état du système et de l'utilisateur sur 4 dimensions :
1. Temporelle : heure, phase de journée, durée de session sur la tâche courante.
2. Cognitive : niveau de focus/fatigue estimé (plein écran, stabilité d'application).
3. Opérationnelle : application active, processus en tâche de fond, charge CPU/RAM.
4. Spatiale : hôte local, connectivité réseau (Tailnet / Localhost).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class PhaseTemporelle(str, Enum):
    MATIN = "matin"          # 06h - 12h
    APRES_MIDI = "apres_midi" # 12h - 18h
    SOIREE = "soiree"        # 18h - 23h
    NUIT = "nuit"            # 23h - 06h


class ChargeCognitive(str, Enum):
    DEEP_WORK = "deep_work"      # Plein écran, application de dev/étude, faible dispersion
    STANDARD = "standard"        # Travail bureautique normal
    DISPERSE = "disperse"        # Changements fréquents d'applications, multi-tâches
    REPOS = "repos"              # Inactivité prolongée


@dataclass(frozen=True)
class DimensionTemporelle:
    timestamp: float
    iso_datetime: str
    phase: PhaseTemporelle
    heure: int
    jour_semaine: str


@dataclass(frozen=True)
class DimensionCognitive:
    charge: ChargeCognitive
    plein_ecran: bool
    stabilite_focus_secondes: float


@dataclass(frozen=True)
class DimensionOperationnelle:
    application: str
    titre_fenetre: str
    processus: str
    cpu_percent: Optional[float]
    ram_percent: Optional[float]


@dataclass(frozen=True)
class DimensionSpatiale:
    hote: str
    est_sur_tailnet: bool
    ip_locale: str


@dataclass(frozen=True)
class ContexteQuadridimensionnel:
    temporel: DimensionTemporelle
    cognitif: DimensionCognitive
    operationnel: DimensionOperationnelle
    spatial: DimensionSpatiale

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_derniere_application = ""
_debut_focus_timestamp = time.time()


def capturer_contexte_quadridimensionnel() -> ContexteQuadridimensionnel:
    """Évalue en temps réel les 4 dimensions de Context Engine sans polling lourd."""
    global _derniere_application, _debut_focus_timestamp
    maintenant = datetime.now()
    ts = time.time()

    # 1. Dimension Temporelle
    h = maintenant.hour
    if 6 <= h < 12:
        phase = PhaseTemporelle.MATIN
    elif 12 <= h < 18:
        phase = PhaseTemporelle.APRES_MIDI
    elif 18 <= h < 23:
        phase = PhaseTemporelle.SOIREE
    else:
        phase = PhaseTemporelle.NUIT

    dim_temporelle = DimensionTemporelle(
        timestamp=ts,
        iso_datetime=maintenant.isoformat(),
        phase=phase,
        heure=h,
        jour_semaine=maintenant.strftime("%A"),
    )

    # 2. Dimension Opérationnelle (via hooks OS Win32)
    app_nom = "Inconnue"
    titre_f = ""
    proc_nom = ""
    plein_ecran = False

    try:
        from context_engine.os_hooks import get_os_hook_manager
        ctx_os = get_os_hook_manager().get_current_context()
        app_nom = ctx_os.get("application") or "Bureau"
        titre_f = ctx_os.get("titre") or ""
        proc_nom = ctx_os.get("processus") or ""
        plein_ecran = bool(ctx_os.get("plein_ecran", False))
    except Exception:
        pass

    cpu_p = None
    ram_p = None
    try:
        import psutil
        cpu_p = psutil.cpu_percent(interval=None)
        ram_p = psutil.virtual_memory().percent
    except Exception:
        pass

    dim_operationnelle = DimensionOperationnelle(
        application=app_nom,
        titre_fenetre=titre_f,
        processus=proc_nom,
        cpu_percent=cpu_p,
        ram_percent=ram_p,
    )

    # 3. Dimension Cognitive (déduite de la stabilité et du plein écran)
    if app_nom != _derniere_application:
        _derniere_application = app_nom
        _debut_focus_timestamp = ts

    duree_focus = max(0.0, ts - _debut_focus_timestamp)

    # Estimation heuristique de charge cognitive
    apps_deep_work = {"antigravity", "code", "cursor", "pycharm", "sublime_text", "terminal", "wt"}
    if plein_ecran or (app_nom.lower() in apps_deep_work and duree_focus > 60):
        charge = ChargeCognitive.DEEP_WORK
    elif duree_focus < 10 and not plein_ecran:
        charge = ChargeCognitive.DISPERSE
    else:
        charge = ChargeCognitive.STANDARD

    dim_cognitive = DimensionCognitive(
        charge=charge,
        plein_ecran=plein_ecran,
        stabilite_focus_secondes=round(duree_focus, 1),
    )

    # 4. Dimension Spatiale
    hote_nom = "localhost"
    sur_tailnet = False
    ip_loc = "127.0.0.1"

    try:
        import socket
        hote_nom = socket.gethostname()
        from context_engine.system_monitor import obtenir_infos_tailscale
        ts_info = obtenir_infos_tailscale()
        sur_tailnet = bool(ts_info.get("actif", False) or ts_info.get("ips"))
    except Exception:
        pass

    dim_spatiale = DimensionSpatiale(
        hote=hote_nom,
        est_sur_tailnet=sur_tailnet,
        ip_locale=ip_loc,
    )

    return ContexteQuadridimensionnel(
        temporel=dim_temporelle,
        cognitif=dim_cognitive,
        operationnel=dim_operationnelle,
        spatial=dim_spatiale,
    )
