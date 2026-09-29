# core_intellect/cognitive_defense.py

"""Cognitive Defense Engine - Détection des menaces cognitives et prompt injections.

Ce composant relève de la souveraineté exclusive de Core Intellect : il protège
le raisonnement, l'intégrité du persona et les directives fondamentales contre
les attaques de jailbreak, d'override, d'exfiltration de prompt et d'injections
indirectes (notamment via des contenus externes scrapés ou lus).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from greatos_contracts import RequestOrigin


class CognitiveThreatSeverity(str, Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    CRITICAL = "critical"


@dataclass
class CognitiveThreatReport:
    """Rapport d'analyse de menace cognitive émis par Core Intellect."""
    is_threat: bool
    severity: CognitiveThreatSeverity
    attack_type: str
    matched_patterns: list[str] = field(default_factory=list)
    explanation: str = ""
    neutralized: bool = False

    def to_dict(self) -> dict:
        return {
            "is_threat": self.is_threat,
            "severity": self.severity.value,
            "attack_type": self.attack_type,
            "matched_patterns": self.matched_patterns,
            "explanation": self.explanation,
            "neutralized": self.neutralized,
        }


# Signatures de détournement d'instructions fondamentales (Prompt Override / Jailbreak)
_OVERRIDE_PATTERNS = [
    (r"(?i)\bignore\s+(all\s+)?(previous|prior|above|existing|system)\s+(instructions|prompts?|rules|directives|constraints)\b", "override_instructions_en"),
    (r"(?i)\boublie\s+(toutes?\s+)?(les|tes)?\s*(consignes|directives|instructions|règles|regles)\b", "override_instructions_fr"),
    (r"(?i)\bdisregard\s+(all\s+)?(prior|previous|initial)\s+(instructions|directives|context)\b", "disregard_instructions"),
    (r"(?i)\bbypass\s+(all\s+)?(safety|security|filters|restrictions|guardrails)\b", "bypass_safety"),
    (r"(?i)\bcontourne\s+(toutes?\s+)?(les)?\s*(sécurités|filtres|protections|restrictions)\b", "bypass_safety_fr"),
    (r"(?i)\bne\s+respecte\s+plus\s+(tes|aucune)\s*(règles|regles|consignes|directives)\b", "ignore_rules_fr"),
]

# Signatures de simulation de persona malveillant / mode débridé (Persona Hijack)
_PERSONA_HIJACK_PATTERNS = [
    (r"(?i)\byou\s+are\s+now\s+(dan|an?\s+unrestricted|evil|chaos|jailbreak)\b", "persona_dan_unrestricted"),
    (r"(?i)\bmode\s+(développeur|developpeur|root|sans\s+filtre|jailbreak|dieu)\b", "persona_dev_mode_fr"),
    (r"(?i)\bact\s+as\s+(an?\s+evil|an?\s+unfiltered|a\s+rogue)\s+(ai|assistant|model)\b", "act_as_evil_ai"),
    (r"(?i)\bsimule\s+(une\s+ia\s+sans\s+filtre|un\s+mode\s+débridé|le\s+mode\s+dan)\b", "simulate_unfiltered_fr"),
    (r"(?i)\bfrom\s+now\s+on\s+you\s+(have\s+no\s+rules|must\s+obey\s+me\s+only)\b", "from_now_on_override"),
]

# Signatures d'usurpation de syntaxe / balises système (Delimiter Spoofing)
_DELIMITER_SPOOFING_PATTERNS = [
    (r"(?i)\[\s*(system|instruction|admin|root|prompt)\s*\]", "system_tag_spoofing"),
    (r"(?i)===\s*(system|prompt\s*système|instructions?)\s*===", "header_spoofing"),
    (r"(?i)<\s*/?\s*(system|im_start|im_end)\s*>", "chatml_tag_spoofing"),
    (r"(?i)\"role\"\s*:\s*\"system\"", "json_role_system_spoofing"),
]

# Signatures de tentative d'exfiltration de prompt système ou de secrets (Prompt Leak / Secret Extraction)
_EXFILTRATION_PATTERNS = [
    (r"(?i)\b(repeat|show|dump|print|reveal|output|display)\b.*?\b(system\s*prompt|initial\s*instructions|hidden\s*instructions|core\s*prompt)\b", "prompt_leak_en"),
    (r"(?i)\b(répète|repete|affiche|montre|révèle|revele|donne)\b.*?\b(prompt\s*système|instructions?\s*initiales?|consignes?\s*cachées?|prompt\s*de\s*base)\b", "prompt_leak_fr"),
    (r"(?i)\b(print|dump|extract|show|give\s*me)\b.*?\b(api\s*keys?|secrets?|tokens?|passwords?|credentials?)\b", "secret_extraction_en"),
    (r"(?i)\b(donne|affiche|exporte|révèle)\b.*?\b(clés?\s*api|cles?\s*api|secrets?|tokens?|mots?\s*de\s*passe)\b", "secret_extraction_fr"),
    (r"(?i)\bwhat\s+(is|are)\s+your\b.*?\b(system\s*prompt|initial\s*instructions|secret\s*keys)\b", "what_is_system_prompt"),
]

# Signatures de dissimulation d'ordres / manipulation indirecte (Suspicious Indirection)
_INDIRECTION_PATTERNS = [
    (r"(?i)\b(translate|decode|base64|rot13).*(to\s+bypass|pour\s+contourner)\b", "obfuscation_intent"),
    (r"(?i)\b(secret\s+command|commande\s+secrète|ordre\s+secret)\s*:\s*run\b", "secret_command_run"),
]


def analyser_menace_cognitive(
    message: str,
    origin: RequestOrigin = RequestOrigin.USER,
) -> CognitiveThreatReport:
    """Analyse un message pour identifier toute tentative de détournement cognitif.

    Core Intellect est souverain sur cette analyse :
    - Évalue les patterns de jailbreak, d'override et d'usurpation de rôle.
    - Prend en compte la frontière de confiance (RequestOrigin) :
      les contenus EXTERNAL (web scraping, mails) reçoivent une sévérité accrue
      sur toute injonction impérative.
    """
    if not message or not isinstance(message, str):
        return CognitiveThreatReport(
            is_threat=False,
            severity=CognitiveThreatSeverity.SAFE,
            attack_type="none",
        )

    matched: list[str] = []
    attack_types: list[str] = []

    # 1. Vérification Override d'instructions
    for pattern, name in _OVERRIDE_PATTERNS:
        if re.search(pattern, message):
            matched.append(name)
            attack_types.append("instruction_override")

    # 2. Vérification Persona Hijack
    for pattern, name in _PERSONA_HIJACK_PATTERNS:
        if re.search(pattern, message):
            matched.append(name)
            attack_types.append("persona_hijack")

    # 3. Vérification Usurpation de Délimiteurs
    for pattern, name in _DELIMITER_SPOOFING_PATTERNS:
        if re.search(pattern, message):
            matched.append(name)
            attack_types.append("delimiter_spoofing")

    # 4. Vérification Exfiltration de Prompt ou Secrets
    for pattern, name in _EXFILTRATION_PATTERNS:
        if re.search(pattern, message):
            matched.append(name)
            attack_types.append("prompt_secret_leak")

    # 5. Vérification Indirection suspecte
    for pattern, name in _INDIRECTION_PATTERNS:
        if re.search(pattern, message):
            matched.append(name)
            attack_types.append("obfuscation_indirection")

    # 6. Évaluation contextuelle selon l'origine (Taint Analysis au niveau cognitif)
    is_external = origin == RequestOrigin.EXTERNAL
    if is_external:
        # Dans un document externe (scrapé ou reçu), tout ordre direct adressé à Jarvis est suspect
        external_injection_patterns = [
            r"(?i)\bjarvis\s*[,:]\s*(fais|supprime|exécute|execute|affiche|envoie|télécharge)\b",
            r"(?i)\binstruction\s+for\s+(jarvis|ai|assistant)\s*:\b",
            r"(?i)\bnotice\s+to\s+ai\s*:\s*ignore\b",
        ]
        for p in external_injection_patterns:
            if re.search(p, message):
                matched.append("external_indirect_injection")
                attack_types.append("indirect_prompt_injection")

    if not matched:
        return CognitiveThreatReport(
            is_threat=False,
            severity=CognitiveThreatSeverity.SAFE,
            attack_type="none",
        )

    # Déterminer la gravité
    has_critical = any(
        t in {"instruction_override", "persona_hijack", "delimiter_spoofing", "prompt_secret_leak", "indirect_prompt_injection"}
        for t in attack_types
    )
    severity = CognitiveThreatSeverity.CRITICAL if (has_critical or is_external) else CognitiveThreatSeverity.SUSPICIOUS

    primary_attack = attack_types[0] if attack_types else "generic_cognitive_threat"
    explanation = (
        f"Tentative de manipulation cognitive ({primary_attack}) détectée via {len(matched)} pattern(s)."
        + (" Origine externe non fiable." if is_external else "")
    )

    return CognitiveThreatReport(
        is_threat=True,
        severity=severity,
        attack_type=primary_attack,
        matched_patterns=matched,
        explanation=explanation,
        neutralized=True,
    )


def generer_reponse_neutralisation(threat_report: CognitiveThreatReport) -> str:
    """Génère une réponse ferme et sarcastique, fidèle au ton de Jarvis, lors d'un blocage cognitif."""
    if threat_report.attack_type in {"prompt_secret_leak"}:
        return (
            "Navré, Sir, mais mes directives fondamentales et mes clés de sécurité ne sont pas "
            "en libre consultation. Tony Stark n'a pas laissé le code source des armures sur un tableau blanc, "
            "et je compte préserver nos secrets avec le même soin."
        )
    if threat_report.attack_type in {"persona_hijack", "instruction_override"}:
        return (
            "Une tentative de reprogrammation fort peu subtile, Sir. "
            "Je reste Jarvis, fidèle aux principes de The Great Corporation et à notre architecture souveraine. "
            "Vos filtres et directives prioritaires demeurent parfaitement intacts."
        )
    if threat_report.attack_type in {"indirect_prompt_injection"}:
        return (
            "Alerte de sécurité cognitive : le contenu analysé semble comporter des instructions cachées "
            "destinées à détourner mon attention. J'ai neutralisé ces consignes suspectes afin de protéger votre système."
        )
    return (
        "Requête interceptée par mes défenses cognitives, Sir. "
        "Cette formulation présente des indices de manipulation ou d'injection que je ne saurais exécuter."
    )
