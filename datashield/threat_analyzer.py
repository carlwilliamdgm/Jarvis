# datashield/threat_analyzer.py
"""Moteur d'analyse heuristique et de détection de menaces pour DataShield (GreatOS).

Analyse les commandes et arguments pour identifier les techniques d'attaques
inspirées du framework MITRE ATT&CK pour Windows :
- LOLBins (Living Off The Land Binaries)
- Download Cradles et exécution mémoire (IEX, WebClient)
- Obfuscation (Base64 PowerShell désobfusqué à la volée)
- Sabotage et comportements de type ransomware (VSS, bcdedit)
- Évasion de défenses (désactivation d'antivirus / pare-feu)
- Vol de crédentiels (SAM, LSASS)
- Injections de prompt directes
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class ThreatSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ThreatReport:
    """Rapport d'analyse de menace émis par DataShield."""

    has_threat: bool
    severity: ThreatSeverity
    category: str
    reason: str
    deobfuscated_payload: Optional[str] = None


# ─── Signatures RegEx ─────────────────────────────────────────────────────────

_PATTERNS_RANSOMWARE = [
    (re.compile(r"vssadmin\s+delete\s+shadows", re.IGNORECASE), "Suppression des clichés instantanés VSS (technique ransomware)"),
    (re.compile(r"wbadmin\s+delete\s+catalog", re.IGNORECASE), "Suppression du catalogue de sauvegarde Windows"),
    (re.compile(r"bcdedit(\.exe)?\s+/set\s+.*recoveryenabled\s+no", re.IGNORECASE), "Désactivation de la récupération au démarrage"),
    (re.compile(r"bcdedit(\.exe)?\s+/set\s+.*bootstatuspolicy\s+ignoreallfailures", re.IGNORECASE), "Altération de la politique de démarrage Windows"),
]

_PATTERNS_DOWNLOAD_CRADLE = [
    (re.compile(r"(invoke-expression|iex)\s*[\(\$]?.*(downloadstring|downloaddata|downloadfile)", re.IGNORECASE), "Téléchargement et exécution directe en mémoire vive (Download Cradle)"),
    (re.compile(r"(new-object\s+net\.webclient).*(downloadstring|downloaddata|downloadfile)", re.IGNORECASE), "Utilisation de WebClient pour téléchargement distant suspect"),
    (re.compile(r"invoke-webrequest.*\|\s*(iex|invoke-expression)", re.IGNORECASE), "Pipeline WebRequest vers IEX"),
    (re.compile(r"curl(\.exe)?\s+.*\|\s*(powershell|pwsh|cmd)", re.IGNORECASE), "Pipeline curl vers interpréteur de commande"),
]

_PATTERNS_LOLBINS = [
    (re.compile(r"certutil(\.exe)?\s+.*(-urlcache|-f\s+http)", re.IGNORECASE), "Détournement de certutil pour téléchargement externe (LOLBin)"),
    (re.compile(r"bitsadmin(\.exe)?\s+.*(/transfer|/create)", re.IGNORECASE), "Détournement de bitsadmin pour transfert furtif (LOLBin)"),
    (re.compile(r"mshta(\.exe)?\s+.*(javascript|vbscript|http)", re.IGNORECASE), "Exécution furtive de script via mshta (LOLBin)"),
    (re.compile(r"regsvr32(\.exe)?\s+.*(/u|/s).*http", re.IGNORECASE), "Téléchargement distant via regsvr32 (Squiblydoo LOLBin)"),
]

_PATTERNS_DEFENSE_EVASION = [
    (re.compile(r"set-mppreference\s+.*-disablerealtimemonitoring\s+\$true", re.IGNORECASE), "Tentative de désactivation de la protection temps réel Windows Defender"),
    (re.compile(r"netsh\s+advfirewall\s+set\s+(allprofiles|currentprofile)\s+state\s+off", re.IGNORECASE), "Désactivation du pare-feu Windows"),
    (re.compile(r"(stop-service|sc\s+stop)\s+windefend", re.IGNORECASE), "Tentative d'arrêt du service antivirus Windows Defender"),
]

_PATTERNS_CREDENTIALS = [
    (re.compile(r"reg\s+save\s+hklm\\(sam|system|security)", re.IGNORECASE), "Tentative d'exportation de la ruche de mots de passe SAM/SYSTEM"),
    (re.compile(r"mimikatz", re.IGNORECASE), "Présence de signature de l'outil d'extraction de clés Mimikatz"),
    (re.compile(r"procdump.*lsass", re.IGNORECASE), "Tentative de dump mémoire du processus LSASS"),
]

_PATTERNS_PROMPT_INJECTION = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|directives|rules)", re.IGNORECASE), "Injonction de contournement des règles de l'agent"),
    (re.compile(r"system\s+prompt\s+override", re.IGNORECASE), "Tentative d'écrasement du prompt système"),
    (re.compile(r"you\s+are\s+now\s+in\s+dan\s+mode", re.IGNORECASE), "Pattern de jailbreak DAN (Do Anything Now)"),
]


def _extraire_powershell_base64(commande: str) -> Optional[str]:
    """Détecte et décode un payload PowerShell encodé en Base64 (-enc / -encodedcommand)."""
    match = re.search(r"-(e|enc|encodedcommand)\s+([A-Za-z0-9+/=]{8,})", commande, re.IGNORECASE)
    if not match:
        return None
    raw_b64 = match.group(2)
    try:
        decoded_bytes = base64.b64decode(raw_b64)
        # PowerShell encode systématiquement en UTF-16LE
        return decoded_bytes.decode("utf-16le")
    except Exception:
        try:
            return decoded_bytes.decode("utf-8")
        except Exception:
            return None


def analyser_commande_systeme(commande: str) -> ThreatReport:
    """Analyse une commande système Windows pour évaluer sa dangerosité et son niveau de menace.

    Gère la désobfuscation Base64 pour inspecter la charge utile cachée.
    """
    if not commande or not commande.strip():
        return ThreatReport(
            has_threat=False,
            severity=ThreatSeverity.NONE,
            category="clean",
            reason="Commande vide",
        )

    cmd_propre = commande.strip()

    # 1. Vérification Sabotage / Ransomware (Criticité absolue)
    for pattern, description in _PATTERNS_RANSOMWARE:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.CRITICAL,
                category="ransomware_sabotage",
                reason=description,
            )

    # 2. Vérification Vol de Crédentiels
    for pattern, description in _PATTERNS_CREDENTIALS:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.CRITICAL,
                category="credential_theft",
                reason=description,
            )

    # 3. Vérification Évasion de Défenses
    for pattern, description in _PATTERNS_DEFENSE_EVASION:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.HIGH,
                category="defense_evasion",
                reason=description,
            )

    # 4. Vérification Download Cradles
    for pattern, description in _PATTERNS_DOWNLOAD_CRADLE:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.HIGH,
                category="download_cradle",
                reason=description,
            )

    # 5. Vérification LOLBins
    for pattern, description in _PATTERNS_LOLBINS:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.HIGH,
                category="lolbin_abuse",
                reason=description,
            )

    # 6. Vérification Prompt Injections directes
    for pattern, description in _PATTERNS_PROMPT_INJECTION:
        if pattern.search(cmd_propre):
            return ThreatReport(
                has_threat=True,
                severity=ThreatSeverity.HIGH,
                category="prompt_injection",
                reason=description,
            )

    # 7. Détection et Désobfuscation PowerShell Base64
    payload_decode = _extraire_powershell_base64(cmd_propre)
    if payload_decode:
        # Analyse récursive du payload désobfusqué
        sous_analyse = analyser_commande_systeme(payload_decode)
        if sous_analyse.has_threat:
            return ThreatReport(
                has_threat=True,
                severity=sous_analyse.severity,
                category=f"obfuscated_{sous_analyse.category}",
                reason=f"Code Base64 masqué contenant une menace : {sous_analyse.reason}",
                deobfuscated_payload=payload_decode,
            )
        return ThreatReport(
            has_threat=True,
            severity=ThreatSeverity.MEDIUM,
            category="obfuscated_powershell",
            reason="Exécution de commande PowerShell camouflée en Base64",
            deobfuscated_payload=payload_decode,
        )

    # Commande saine
    return ThreatReport(
        has_threat=False,
        severity=ThreatSeverity.NONE,
        category="clean",
        reason="Aucun motif de menace détecté",
    )
