"""Runtime safety zones for Jarvis.

Jarvis uses a two-tier policy:
- protected/system zones are detected dynamically by ZoneMapper and blocked;
- user-space actions do not require confirmation by this module.

ZONE_MAP self-initializes at import time, refreshes stale data automatically,
and avoids hardcoded Windows paths by deriving roots from environment variables
or platform APIs when available.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from core.paths import JARVIS_DIR

USE_FALLBACK = False


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

        roots.append(Path.home())
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
    return ZONE_MAP.est_protege(path)


def action_requiert_confirmation(path: Path) -> bool:
    return False


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
