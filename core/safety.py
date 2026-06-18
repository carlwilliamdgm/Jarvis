#core/safety.py

"""Runtime safety zones for Jarvis.

Jarvis uses a two-tier policy:
- protected/system zones are detected dynamically by ZoneMapper and blocked;
- user-space actions do not require confirmation by this module.

ZONE_MAP self-initializes at import time, refreshes stale data automatically,
and avoids hardcoded Windows paths by deriving roots from environment variables
or platform APIs when available.

Mode Stark (!S) : contrôle l'accès aux zones sensibles et système.
- mode_stark_actif = False (défaut) : zones système et sensibles bloquées
- mode_stark_actif = True (!S) : zones système et sensibles accessibles
- JARVIS_DIR toujours bloqué — exception absolue, jamais levée
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from core.paths import JARVIS_DIR, HOME

USE_FALLBACK = False

# ============================================================================
# MODE STARK - FLAG DE SESSION
# ============================================================================

_mode_stark_actif = False


def activer_mode_stark() -> None:
    """Active le mode Stark (!S)."""
    global _mode_stark_actif
    _mode_stark_actif = True


def desactiver_mode_stark() -> None:
    """Désactive le mode Stark."""
    global _mode_stark_actif
    _mode_stark_actif = False


def est_mode_stark_actif() -> bool:
    """Retourne True si le mode Stark est actif."""
    return _mode_stark_actif


def _bootstrap_import(module_name: str, package_name: str | None = None):
    global USE_FALLBACK
    try:
        return importlib.import_module(module_name)
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name or module_name, "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=True,
            )
            return importlib.import_module(module_name)
        except Exception:
            USE_FALLBACK = True
            return None


psutil = _bootstrap_import("psutil")
win32api = _bootstrap_import("win32api", "pywin32") if os.name == "nt" else None
win32security = _bootstrap_import("win32security", "pywin32") if os.name == "nt" else None


class ZoneMapper:
    """Maps critical zones from live environment and optional OS metadata."""

    STALE_AFTER = timedelta(hours=1)
    FILE_ATTRIBUTE_SYSTEM = 0x4

    def __init__(self):
        self.protected_roots = frozenset()
        self.last_refresh = datetime.min
        self.refresh()

    def refresh(self):
        roots = []
        env_names = (
            "SystemRoot",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMDATA",
            "COMMONPROGRAMFILES",
        )
        for name in env_names:
            value = os.environ.get(name)
            if value:
                roots.append(Path(value).expanduser())

        roots.append(JARVIS_DIR)

        resolved = []
        for root in roots:
            try:
                resolved.append(root.resolve(strict=False))
            except OSError:
                continue

        self.protected_roots = frozenset(resolved)
        self.last_refresh = datetime.now()

    def _refresh_if_stale(self):
        if datetime.now() - self.last_refresh > self.STALE_AFTER:
            self.refresh()

    def _under_protected_root(self, path: Path) -> bool:
        for root in self.protected_roots:
            try:
                resolved = path.resolve(strict=False)
                if resolved == root or resolved.is_relative_to(root):
                    return True
            except OSError:
                continue
        return False

    def _has_system_attribute(self, path: Path) -> bool:
        if USE_FALLBACK or win32api is None:
            return False
        try:
            attributes = win32api.GetFileAttributes(str(path))
            return bool(attributes & self.FILE_ATTRIBUTE_SYSTEM)
        except Exception:
            return False

    def _owned_by_trusted_installer(self, path: Path) -> bool:
        if USE_FALLBACK or win32security is None:
            return False
        try:
            security = win32security.GetFileSecurity(str(path), win32security.OWNER_SECURITY_INFORMATION)
            owner_sid = security.GetSecurityDescriptorOwner()
            name, domain, _ = win32security.LookupAccountSid(None, owner_sid)
            owner = f"{domain}\\{name}".lower() if domain else str(name).lower()
            return "trustedinstaller" in owner
        except Exception:
            return False

    def _held_by_system_process(self, path: Path) -> bool:
        if USE_FALLBACK or psutil is None:
            return False
        try:
            target = path.resolve(strict=False)
        except OSError:
            return False

        for proc in psutil.process_iter(("username", "open_files")):
            try:
                username = (proc.info.get("username") or "").lower()
                if not (username == "system" or username.endswith("\\system")):
                    continue
                for opened in proc.info.get("open_files") or []:
                    opened_path = Path(opened.path).resolve(strict=False)
                    if opened_path == target or opened_path.is_relative_to(target):
                        return True
            except (OSError, psutil.Error):
                continue
        return False

    def est_protege(self, path: Path) -> bool:
        self._refresh_if_stale()
        try:
            resolved = Path(path).expanduser().resolve(strict=False)
        except OSError:
            resolved = Path(path).expanduser()

        if self._under_protected_root(resolved):
            return True
        if USE_FALLBACK:
            return False
        return (
            self._has_system_attribute(resolved)
            or self._owned_by_trusted_installer(resolved)
            or self._held_by_system_process(resolved)
        )


ZONE_MAP = ZoneMapper()


def action_bloquee(path: Path) -> bool:
    """
    Détermine si une action est bloquée sur un chemin donné.
    
    Hiérarchie des permissions :
    - mode_stark_actif = False (défaut) :
      * Zones système bloquées : SystemRoot, Program Files, ProgramData
      * Zones sensibles bloquées : Desktop, Documents, Downloads, home racine
      * JARVIS_DIR bloqué
    
    - mode_stark_actif = True (!S) :
      * Zones sensibles accessibles
      * Zones système accessibles
      * JARVIS_DIR toujours bloqué — exception absolue, jamais levée
    """
    # JARVIS_DIR est TOUJOURS bloqué, même en mode Stark
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        if resolved == JARVIS_DIR or resolved.is_relative_to(JARVIS_DIR):
            return True
    except OSError:
        pass
    
    # En mode Stark, seul JARVIS_DIR reste bloqué
    if est_mode_stark_actif():
        return False
    
    # Mode normal : vérifier les zones système et sensibles
    return ZONE_MAP.est_protege(path) or _est_zone_sensible(path)


def _est_zone_sensible(path: Path) -> bool:
    """
    Détermine si un chemin est dans une zone sensible.
    
    Zones sensibles (bloquées en mode normal) :
    - Desktop
    - Documents
    - Downloads
    - home racine
    """
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        home_resolved = HOME.resolve()
        
        # Zones sensibles directes
        zones_sensibles = [
            home_resolved,
            (home_resolved / "Desktop").resolve(),
            (home_resolved / "Documents").resolve(),
            (home_resolved / "Downloads").resolve(),
        ]
        
        for zone in zones_sensibles:
            if resolved == zone or resolved.is_relative_to(zone):
                return True
        
        return False
    except OSError:
        return False


def action_requiert_confirmation(path: Path) -> bool:
    """
    Détermine si une action nécessite une confirmation utilisateur.
    
    Cette fonction est utilisée par les outils pour demander confirmation
    avant d'exécuter des actions sensibles.
    
    En mode Stark, aucune confirmation n'est requise (l'utilisateur a déjà
    explicitement activé le mode privilégié).
    """
    if est_mode_stark_actif():
        return False
    
    # Les actions sur les zones sensibles nécessitent une confirmation
    return _est_zone_sensible(path)


def action_requiert_verrou(path: Path) -> bool:
    sensitive = {
        Path.home().resolve(),
        (Path.home() / "Desktop").resolve(),
        (Path.home() / "Documents").resolve(),
        (Path.home() / "Downloads").resolve(),
    }
    return Path(path).resolve(strict=False) in sensitive


def chemin_autorise(chemin: str, doit_exister: bool = False) -> Path:
    """Valide et retourne le chemin. Vérifie l'existence si demandé."""
    if not chemin or not str(chemin).strip():
        raise ValueError("Chemin vide.")

    path = Path(chemin).expanduser()
    if not path.is_absolute():
        path = JARVIS_DIR / path

    if doit_exister:
        path = path.resolve(strict=True)
    else:
        parent = path.parent.resolve(strict=False)
        path = parent / path.name

    return path


def suppression_requiert_confirmation(path: Path) -> bool:
    return action_requiert_confirmation(path)


def racine_trop_large(path: Path) -> bool:
    # DEPRECATED: use action_bloquee instead.
    return action_bloquee(path)


def niveau_depuis(parent: Path, enfant: Path) -> int | None:
    # DEPRECATED: kept for backward compatibility.
    try:
        relatif = enfant.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return None
    return len(relatif.parts)
