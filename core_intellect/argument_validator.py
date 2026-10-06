# core_intellect/argument_validator.py

"""Argument Validator & Self-Correction - Validation des paramètres d'outils par Core Intellect.

Core Intellect est souverain sur le raisonnement et la formulation des intentions d'actions.
Ce composant valide et auto-corrige les paramètres d'outils générés par le LLM
avant qu'ils ne soient transmis à DataShield et au dispatcher d'exécution.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any


# Dictionnaire de normalisation des alias fréquents générés par les LLMs
_ALIAS_PARAMETRES = {
    "executer_commande": {"cmd": "commande", "command": "commande", "script": "commande"},
    "executer_powershell": {"cmd": "commande", "command": "commande", "script": "commande", "ps1": "commande"},
    "noter": {"contenu": "note", "texte": "note", "message": "note"},
    "creer_fichier": {"path": "chemin", "fichier": "chemin", "text": "contenu", "data": "contenu"},
    "lire_fichier": {"path": "chemin", "fichier": "chemin"},
    "supprimer_fichier": {"path": "chemin", "fichier": "chemin"},
    "creer_dossier": {"path": "chemin", "dossier": "chemin"},
    "supprimer_dossier": {"path": "chemin", "dossier": "chemin"},
    "lister_dossier": {"path": "chemin", "dossier": "chemin"},
    "recherche_web": {"query": "requete", "q": "requete", "recherche": "requete"},
    "chiffrer_valeur": {"text": "texte", "valeur": "texte", "secret": "texte"},
    "dechiffrer_valeur": {"blob": "blob_chiffre", "data": "blob_chiffre", "texte_chiffre": "blob_chiffre"},
}


@dataclass
class ValidationResult:
    is_valid: bool
    outil: str
    arguments: dict[str, Any]
    corrections_applied: list[str]
    missing_required: list[str]
    error_message: str = ""


def valider_et_corriger_arguments(outil: str, args: dict[str, Any] | None) -> ValidationResult:
    """Valide et redresse les arguments d'un outil avant transmission à DataShield.

    1. Normalise les alias de paramètres fréquents.
    2. Inspecte la signature de la fonction dans OUTILS.
    3. Vérifie la présence des arguments positionnels/obligatoires.
    """
    from core_intellect.tool_registry import OUTILS

    if outil not in OUTILS:
        return ValidationResult(
            is_valid=False,
            outil=outil,
            arguments=args or {},
            corrections_applied=[],
            missing_required=[],
            error_message=f"Capacité ou outil inconnu dans le registre : {outil}",
        )

    fonction = OUTILS[outil]
    args_propres = dict(args or {})
    corrections: list[str] = []

    # 1. Redressement des alias connus
    alias_map = _ALIAS_PARAMETRES.get(outil, {})
    for alias, canonique in alias_map.items():
        if alias in args_propres and canonique not in args_propres:
            args_propres[canonique] = args_propres.pop(alias)
            corrections.append(f"Paramètre '{alias}' normalisé en '{canonique}'")

    # 2. Inspection de la signature
    try:
        sig = inspect.signature(fonction)
    except (TypeError, ValueError):
        # Si non inspectable, accepter tel quel
        return ValidationResult(
            is_valid=True,
            outil=outil,
            arguments=args_propres,
            corrections_applied=corrections,
            missing_required=[],
        )

    # 3. Vérification des paramètres requis
    missing_required: list[str] = []
    for nom_param, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            if param.default is inspect.Parameter.empty:
                if nom_param not in args_propres:
                    missing_required.append(nom_param)

    is_valid = len(missing_required) == 0
    err_msg = f"Paramètre(s) requis manquant(s) pour '{outil}' : {', '.join(missing_required)}" if missing_required else ""

    return ValidationResult(
        is_valid=is_valid,
        outil=outil,
        arguments=args_propres,
        corrections_applied=corrections,
        missing_required=missing_required,
        error_message=err_msg,
    )
